# Copyright (C) 2021  Malik Irain
# This file is part of econect-i8-utils.
#
# econect-i8-utils is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# econect-i8-utils is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with econect-i8-utils.  If not, see <http://www.gnu.org/licenses/>.

import atexit
import bisect
import logging
import multiprocessing
import queue
import signal
import statistics
import threading
import time
from datetime import datetime
from enum import Enum
from functools import partial
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from multiprocessing import Manager
from os import remove, fstat
from os.path import basename
from pathlib import Path
from shutil import copyfileobj, rmtree
from time import time_ns
from typing import IO, Any, Dict, List, Optional, Union, cast

from digi.xbee.devices import XBee16BitAddress, XBee64BitAddress, XBeeDevice
from digi.xbee.exception import (InvalidOperatingModeException,
                                 TimeoutException, TransmitException,
                                 XBeeException)
from digi.xbee.models.options import TransmitOptions
from digi.xbee.packets.aft import ApiFrameType

from econect.formats import F8Wrapper
from econect.qos import DummyTrameCounter, FileTrameCounter, TrameCounter
from econect.type import Singleton


class Protocol_ID(Enum):
	I8DP = 0x00
	I8TP = 0xA0
	I8RP = 0xF0



from econect.protocol.I8DP import I8DP_Trame
from econect.protocol.I8RP import I8RP_Trame
from econect.protocol.I8TP import I8TP_Trame

'''
	I8TL : Transport Layer for IEEE 802.15.4

	This modules provides two classes.

	The first one is the `DataSender` class that allows users to easily send 
	data over an IEEE 802.15.4 link, using digi XBee modules.

	For that, two methods are available:
			- notify_data_to_send: to send raw bytes data, in a known format
			 for the receiver (e.g. NeoCayenneLPP).

			- notify_file_to_send: to send a file stored on the drive by giving its
			path.

	In any case, notified data is stored in a temporary file before beeing sent.

	
	The second one is the `DataReceiver` class that allos user to easily receive
	data over an IEEE 802.15.4 link, using digi XBee modules.

	For that, one method is available:
			- get_data_filename: gives the user a filename to be opened contained
			reassembled received data.
	
	In can be denoted that this class starts a new thread for each `connection`
	from new devices and stops them after a while if no data was transmitted.

	Both classes are Singletons (because of the shared XBeeDevice resource),so all 
	instances are in fact the same. Be carefull, arguments given to the constructor
	are only used on the first 'nstanciation. A user can 'instanciate' one like a 
	normal object, but it will always be the same. These classes also contain a 
	Process that starts on creation, in order to be able to notify data/file 
	availability from/to the main Process without being blocked while trying to 
	send/receive them.

'''



def i8tl_send_trame(device : XBeeDevice, destination_addr : Union[XBee16BitAddress,XBee64BitAddress], data : bytes) -> None:
	'''
	Sends provided `data` through `device` to `destination_addr` by handling
	all exceptions that may arise. 
	'''
	try:
		if isinstance(destination_addr, XBee16BitAddress):
			device._send_data_16(destination_addr, data, TransmitOptions.DISABLE_ACK.value)			
		else:
			device._send_data_64(destination_addr, data, TransmitOptions.DISABLE_ACK.value)
	except ValueError as ve:
		if destination_addr is None:
			logger.error('[I8TL] Address was None. Could not send data.')
		elif data is None:
			logger.error('[I8TL] Trame was None. Could not send data.')
		logger.error(f'[I8TL] {ve}')
	except TimeoutException as te:
		logger.error(f'Configured timeout should be None (nolimit) but is {device.get_sync_ops_timeout()} and was exceeded.')
		logger.error(f'[I8TL] {te}')
	except InvalidOperatingModeException as iome:
		logger.error('[I8TL] Device should be in API mode but is not.')
		logger.error(f'[I8TL] {iome}')
	except TransmitException as te:
		logger.error(f'[I8TL] {te}')
	except XBeeException as xe:
		logger.error('[I8TL] Device communication interface is closed (maybe unplugged?).')
		logger.error(f'[I8TL] {xe}')




logger = logging.getLogger('i8-utils')

def get_Protocol_ID(first_byte : int) -> Protocol_ID:
	'''
	Exctract the Protocol ID from the given byte
	'''
	return Protocol_ID(first_byte & 0xF0)

def _get_chunk_count(fileno : int) -> int:
	'''
	Count how much chunks of `PAYLOAD_MAX_LEN` 
	will be made with a file from its `fileno`.
	'''
	size = fstat(fileno).st_size
	chunk_count = (size + I8DP_Trame.PAYLOAD_MAX_LEN - 1)//I8DP_Trame.PAYLOAD_MAX_LEN

	return chunk_count


def _prepare_logger(base_log_level : int, log_dir : str, filename : str):
	'''
	Create ;
		- a rotating logger file that catches all whose location depends 
		 on `log_dir` and `filename`
		- a stream logger on stderr set a `base_log_level` level.

	Also disables digi.xbee loggers and urllib3.connectionpool
	'''
	rfh = RotatingFileHandler(f'{log_dir}/{time.time_ns()}-i8_{filename}.log', maxBytes=65536,backupCount=1)
	rfh.setLevel(logging.NOTSET)

	sh = StreamHandler()
	sh.setLevel(base_log_level)

	# logger.setLevel(logging.NOTSET)
	# logger.addHandler(rfh)
	# logger.addHandler(sh)

	logging.basicConfig(level=logging.NOTSET, handlers=[rfh, sh])

	logging.getLogger("digi.xbee.devices").disabled = True
	logging.getLogger("digi.xbee.sender").disabled = True
	logging.getLogger("digi.xbee.reader").disabled = True
	logging.getLogger("urllib3.connectionpool").disabled = True

class DataSender(metaclass=Singleton):
	__slots__ = ('_process', '_device', '_coord_addr', '_queue', 
		'_stop_event', '_xbee_init_event', '_tmp_dir', '_log_dir',
		'_del_dir', '_retries', '_response_timeout','_timestamp_delta',
		'_delta_lifetime', '_trame_counter')

	def __init__(self, 
		path             : str              = '/dev/ttyUSB0',
		speed            : int              = 230400,
		tmp_dir          : str              = '/tmp/datasender',
		log_dir          : str              = './log',
		del_dir          : bool             = False,
		coord_addr       : XBee64BitAddress = None,
		retries          : int              = 1,
		self_stop        : bool             = False,
		response_timeout : int              = 3,
		qos_info         : bool             = False,
		base_log_level   : int              = logging.NOTSET):
		

		# Create log dir if not existing
		self._log_dir = log_dir + '/' 
		Path(self._log_dir).mkdir(parents=True, exist_ok=True)

		_prepare_logger(base_log_level, self._log_dir, 'datasender')
		

		# Create tmp dir if not existing
		self._tmp_dir = tmp_dir + '/' 
		Path(self._tmp_dir).mkdir(parents=True, exist_ok=True)

		self._del_dir = del_dir

		self._retries = retries
		self._response_timeout = response_timeout
		self._delta_lifetime = -1
		self._timestamp_delta = Manager().Value('i', 0)

		self._queue           : multiprocessing.Queue             = multiprocessing.Queue()
		self._stop_event      : multiprocessing.synchronize.Event = multiprocessing.Event()
		self._xbee_init_event : multiprocessing.synchronize.Event = multiprocessing.Event()

		

		# Count trames and retranmission if qos_info is enabled, otherwise use a dummy counter
		self._trame_counter   : TrameCounter = FileTrameCounter(f'{self._log_dir}{time.time_ns()}-retransmissions.log') if qos_info else DummyTrameCounter()

		if self_stop:
			atexit.register(self.stop)
		

		# Start the sending process
		self._process = multiprocessing.Process(target=self.__run, args=(path, speed, coord_addr))
		self._process.start()


	@property
	def timestamp_delta(self):
		'''
		Returns the delta with server clock
		'''
		return self._timestamp_delta.value
	
	@property
	def timestamp(self) -> int:
		'''
		Returns the current timestamp plus delta
		'''
		return time.time_ns() + self.timestamp_delta

		

	def notify_data_to_send(self, data: bytes) -> None:
		'''
		Notify the data sender process that  new data is to be send.
		Data is saved in a temporary location in form of a file.
		'''
		self._xbee_init_event.wait()

		filename = self._tmp_dir + str(time_ns()) + '-' + data.hex()[-8:] + ".bin"

		with open(filename, 'wb') as file:
			file.write(data)

		self._queue.put(filename)
		logger.info(f'[I8TL] DataSender received a notification for {filename} (data)')

	def notify_file_to_send(self, filename: str) -> None:
		'''
		Notify the data sender process that a new file is to be send.
		The file is encapsulated in a F8Wrapper and saved in a temporary
		location, allowing to keep its filename through the transfert.
		'''
		self._xbee_init_event.wait()

		new_filename = self._tmp_dir + str(time_ns()) + '-' + basename(filename) + ".bin"

		with F8Wrapper(filename, 'rb') as fsrc, open(new_filename, 'wb') as fdst:
			copyfileobj(fsrc, fdst)
		
		self._queue.put(new_filename)
		logger.info(f'[I8TL] DataSender received a notification for {filename} (file)')

	def is_sending(self) -> bool:
		'''
		Returns True if the sender queue is empty, False otherwise.
		Result correctness is not guaranteed.
		'''
		return not self._queue.empty()
	

	def stop(self) -> None:
		'''
		Notify the process to stop and wait for it
		to do it (after it finished its transfert)
		'''
		logger.info("[I8TL] Exiting. Waiting for DataSender process to stop.")
		self._stop_event.set()
		self._process.join()
		

	def _init_device_coord_addr_and_timestamp_delta(self,  path: str, speed: int, coord_addr : XBee64BitAddress):
		'''
		Open the XBeeDevice, get the 64 bit address of the coordinator and sync the clock by
		'''
		self._device = XBeeDevice(path, speed)
		self._device.open()
		self._device.set_sync_ops_timeout(None)

		logger.info(f'[I8TL] Local 16 bits address: {self._device.get_16bit_addr()}')
		logger.info(f'[I8TL] Local 64 bits address: {self._device.get_64bit_addr()}')

		self._coord_addr = coord_addr

		i = 1
		
		while not self._coord_addr and not self._stop_event.is_set():
			self._coord_addr = I8RP_Trame().send(self._device)
			if self._coord_addr is None:
				logger.warning(f'[I8TL] Could not get IEEE 802.15.4 Coordinator 64 bits address (try {i}).')
				i+= 1

		if self._stop_event.is_set():
			return

		logger.info(f'[I8TL] Coordinator 64 bits address: {self._coord_addr}')
		
		self._update_timestamp_delta()
		self._xbee_init_event.set()

	def _timestamp_delta_is_valid(self):
		'''
		Checks if the timestamp delta is still valid
		(its lifetime is not expired)
		'''
		return time.time_ns() <= self._delta_lifetime

	def _update_timestamp_delta(self, validity_in_hours : int=24):
		'''
		Update timestamp
		'''
		delta_list = []
		for _ in range(10):
			delta = I8TP_Trame().send(self._device, self._coord_addr, timeout=self._response_timeout)
			if delta is not None:
				delta_list.append(delta)
		self._timestamp_delta.value = round(statistics.mean(delta_list)) 

		if validity_in_hours == 0:
			# Valid "forever" (2554-07-22 01:34:33.709553)
			self._delta_lifetime = 2**64
		else:
			# convert hours to ns. Valid but leap seconds introduce a slow shift
			self._delta_lifetime = time.time_ns() + validity_in_hours * int(3.6e+12) 
		logger.info(f'[I8TL] Got new timestamp_delta ({self._timestamp_delta.value}), valid until {datetime.fromtimestamp(self._delta_lifetime*1e-9)}')


	def _resend_chunks(self, trames_to_resend : List[I8DP_Trame]) -> bool:
		'''
		Individualy resend the trames that weren't acknowledged (`trames_to_send`)
		waiting for individual acknowledgements.

		Returns True if everything was send and acknowledged, False otherwise.
		'''
		logger.info(f'[I8TL] Trying to resend {len(trames_to_resend)} trames.')

		# No `for .. in` loop because trames_to_resend may be
		# modified in the loop (some elements may receive a late ACK)
		while len(trames_to_resend) > 0:
			ack = False
			
			# All trames should be individualy acknowledged
			a_trame = trames_to_resend[0]
			a_trame.set_needs_ack()
			tries = 1
			while not ack and tries <= self._retries:
				logger.info(f'[I8TL] Resending trame {a_trame.seq}. (try {tries}/{self._retries})')
				i8dp_ack = a_trame.send(self._device, self._coord_addr, timeout=self._response_timeout)
				self._trame_counter.inc_retrans()
				if i8dp_ack is not None:
					# Sequence number of trames are retrieved in `ack_list`
					# The intersection between this list and the sequence numbers
					# `trames_to_resend` are to be removed
					ack_list = [i8dp_ack.seq] + i8dp_ack.ack_list
					trames_to_remove = list(set(ack_list) & set(trames_to_resend))
					logger.info(f'[I8TL] Trames {trames_to_remove} correctly acknowledged.')
					ack = True


					for a_trame_to_remove in trames_to_remove:
						# It can fail if the same sequence number appears several times...
						# But it shouldn't and is not so problematic!
						try:
							trames_to_resend.remove(cast(I8DP_Trame, a_trame_to_remove))
						except ValueError as ve:
							logger.error(f'[I8TL] Could not remove {a_trame_to_remove}, not in {trames_to_resend} ({ve})')
				else: 
					logger.warning(f'[I8TL] Acknowledgment not received for trame {a_trame.seq}.')
				tries +=1
			
			if not ack:
				return False
		return True



	def _send_file(self, file : IO[bytes]) -> bool:
		'''
		The method to send an already opened `file`

		Returns True when a file was fully sent, False otherwise.
		'''
		chunk_count = _get_chunk_count(file.fileno())
		logger.info(f'[I8TL] {chunk_count} chunks are needed to send {file.name}')
		
		trames_sent : List[I8DP_Trame] = []	

		# Each transmission should start by a RST trame!
		# And receive a RST trame in return
		reset = False
		while not reset:
			logger.info('[I8TL] Sending RST Trame.')
			i8dp_rst_ack = I8DP_Trame.rst_trame().send(self._device, self._coord_addr, timeout=self._response_timeout)
			reset = (i8dp_rst_ack is not None) and i8dp_rst_ack.is_rst

		for i, chunk in enumerate(iter(partial(file.read, I8DP_Trame.PAYLOAD_MAX_LEN), b''), 1):
			# Building a trame around a chunk:
			#  - BEGIN is set for the first sent trame and not set otherwise
			#  - MORE_FRAG is set for the last sent trame and not set otherwise
			#  - NEED_ACK is set in one of the following cases:
			# 	 - It is the last trame of a burst (`BURST_MAX_LEN` trames sent without ACK)
			#     - It is the last trame to end the transfert
			#     - Its sequence number is the last one before going back to 0 (So that the 
			# 	   ordering stays ok, on the receiver side (0 < 255 but Trame 0 may follow Trame 255))
			trame = I8DP_Trame.data_trame(chunk, begin=(i == 1), need_ack=((i%I8DP_Trame.BURST_MAX_LEN == 0) or (i == chunk_count)), more_fragments=(i != chunk_count))
			if trame.seq == (I8DP_Trame.SequenceGenerator.LIMIT - 1):
				trame.set_needs_ack()

			logger.info(f'[I8TL] Trying to send chunk {i} of {chunk_count} with in trame [#SEQ:{trame.seq},NEEDS_ACK:{trame.needs_ack},MORE_FRAG:{trame.more_frag}]')
			i8dp_ack = trame.send(self._device, self._coord_addr, timeout=self._response_timeout)
			
			self._trame_counter.inc_send()
			
			if not trame.needs_ack:
				trames_sent.append(trame)
			else:
				# When a trame needs ACK, i8dp_ack should not be empty!
				# If it is, we resend everything from the beginning of the
				# burst and the current trame: we know the current trame
				# may not have been received (because no ACK were received)
				# and we don't know which other trames were not received.
				to_resend = []
				if i8dp_ack is None:
					to_resend = trames_sent
					to_resend.append(trame)
					logger.warning(f'[I8TL] Acknowledgment for trames {[trame.seq] + [trame.seq for trame in trames_sent]} is needed but was not received.')
				else:
					# The trames to resend again are the ones sent in the last burst
					# that were not included in this acknowledgement.
					to_resend = [trames_sent[j] for j in range(len(trames_sent)) if trames_sent[j].seq not in i8dp_ack.ack_list]
					if to_resend:
						logger.warning(f'Acknowledgment for trames {[trame.seq] + [trame.seq for trame in trames_sent]} is needed but was partially received (Trames {[trame.seq for trame in to_resend]} will be resend)')
					else:
						logger.info(f'[I8TL] Acknowledgment for trames {[trame.seq] + [trame.seq for trame in trames_sent]} was succesfuly received.')
				
				sent = self._resend_chunks(to_resend)
				
				if not sent:
					return False
				trames_sent = []
		return True
		
	def __run(self, path : str, speed : int, coord_addr : XBee64BitAddress):
		'''
		Starting point of the internal subprocess.

		It handles getting the temporary filenames, opening and sending them.
		'''
		if multiprocessing.parent_process() is None:
			logger.error("[I8TL]Tried to call run() method from main process.")
			return
		
		logger.info("[I8TL] DataSender process created")
		
		# SIGINT is disabled to handle termination in a proper way
		signal.signal(signal.SIGINT, signal.SIG_IGN)

		self._init_device_coord_addr_and_timestamp_delta(path=path, speed=speed, coord_addr=coord_addr)

		# To quit we need to wait for the `stop()` method to have been
		# called and set `_stop_event`
		while not self._stop_event.is_set():
			if not self._timestamp_delta_is_valid():
				self._update_timestamp_delta()
			try:
				file_sent = False

				# The timeout is here so the loop can check
				# for `_stop_event` event when `_queue` is empty
				filename = self._queue.get(timeout=1)
				logger.info(f'[I8TL] Trying to send {filename}')
						
				with open(filename, 'rb') as file:
					file_sent = self._send_file(file)	
				
				# When a file is sent, we remove it's temporary version
				# otherwise we will try to send it again later ...
				if file_sent:	
					logger.info(f'[I8TL] Sent file {filename}')
					remove(filename)
				
				else:
					logger.warning(f'[I8TL] Could not send {filename}, putting it back into the queue.')
					self._queue.put(filename)
			except queue.Empty:
				# When timeout expired, nothing to worry about
				pass
				
		logger.info("[I8TL] DataSender process exiting")
		
		# cleaning up data and device when exiting
		if self._del_dir:
			logger.info(f"[I8TL] Recursively removing temporary folder and files (in {self._tmp_dir})")
			rmtree(self._tmp_dir, ignore_errors=True)

		self._device.close()


class DataReceiver(metaclass=Singleton):

	class ReceiverThreadPool():
		__slots__ = ('_tmp_dir', '_inactive_time_limit', '_threads', '_thread_stop_events',
			'_thread_trame_reception_queues', '_assembled_data_queue', '_notify_lock',
			 '_responses_trames_queue', '_ack_thread_stop_event', '_ack_thread')

		def __init__(self, device : XBeeDevice, assembled_data_queue : queue.Queue, tmp_dir : str, inactive_time_limit : int):
			self._tmp_dir = tmp_dir
			self._inactive_time_limit = inactive_time_limit
			self._notify_lock = threading.Lock()
			self._assembled_data_queue = assembled_data_queue

			self._threads : Dict[XBee64BitAddress, threading.Thread] = {}
			self._thread_stop_events : Dict[XBee64BitAddress, threading.Event] = {}
			self._thread_trame_reception_queues : Dict[XBee64BitAddress, queue.Queue] = {}

			self._responses_trames_queue : queue.Queue = queue.Queue()
			self._ack_thread_stop_event : threading.Event = threading.Event()
			self._ack_thread : threading.Thread = threading.Thread(target=DataReceiver.ReceiverThreadPool.__run_send_responses, args=(device, self._ack_thread_stop_event, self._responses_trames_queue))

			self._ack_thread.start()

		@staticmethod
		def __run_send_responses(device : XBeeDevice, stop_event : threading.Event, responses_trames_queue : queue.Queue):
			# logger = logging.getLogger('ResponderThread')
			# should change logger output
			while not stop_event.is_set():
				try:
					i8tl = responses_trames_queue.get(timeout=1)
					i8tl_send_trame(device, i8tl['to'], i8tl['trame'].to_bytes())
					
				except queue.Empty:
					pass

		@staticmethod
		def __run(tmp_dir : str, inactive_time_limit : int, stop_event : threading.Event, trame_reception_queue : queue.Queue, assembled_data_queue : queue.Queue, responses_trames_queue : queue.Queue):
			RANGE_0_BURST_MAX_LEN = list(range(0, I8DP_Trame.BURST_MAX_LEN))
			RANGE_LIMIT_BURST_MAX_LEN = list(range(I8DP_Trame.SequenceGenerator.LIMIT - I8DP_Trame.BURST_MAX_LEN, I8DP_Trame.SequenceGenerator.LIMIT))
			transmission_in_progress = False
			elapsed_time_without_trame = 0

			fragment_burst : List[I8DP_Trame] = []
			seq_ack_list : List[int] = []
			expected_seq : int = 0
			sequence : I8DP_Trame.SequenceGenerator
			current_filename  : str = ''
			current_file : Optional[IO[bytes]] = None
			chunks_to_write : List[bytes] = []
			should_end : bool = False

			# logger = logging.getLogger(f'DataReceiver@{threading.currentThread().getName()}')
			# Change logger output
			logger.info("Starting thread because a message was received.")
			while not stop_event.is_set() or transmission_in_progress:
				try:
					data = trame_reception_queue.get(timeout=1)
					elapsed_time_without_trame = 0

					try:
						protocol_id = get_Protocol_ID(data['data'][0])
						if   protocol_id == Protocol_ID.I8RP:
								logger.info("[I8RP] Received request. Answering")
								responses_trames_queue.put({'trame' : I8RP_Trame(), 'to' : data['from']})
						elif protocol_id == Protocol_ID.I8TP:
							logger.info("[I8TP] Received trame.")
							i8tp_trame = I8TP_Trame.from_bytes(data['data'])
							if i8tp_trame.is_req:
								logger.info("[I8TP] Received request. Answering")
								responses_trames_queue.put({'trame' : I8TP_Trame(I8TP_Trame.I8TP_Type.I8TP_TIME_RES), 'to' : data['from']})
						elif protocol_id == Protocol_ID.I8DP:
							i8dp_trame = I8DP_Trame.from_bytes(data['data'])

							ignore_trame = False
							# if it's an ack we ignore it
							if i8dp_trame.is_rst:
								transmission_in_progress = False
								logger.info(f"[I8DP] Received RST Trame. Sending RST back.")
								responses_trames_queue.put({'trame' : I8DP_Trame.rst_trame(), 'to' : data['from']})
								if current_file is not None:
									current_file.close()
									remove(current_file.name)
									current_file = None	
							
							elif  i8dp_trame.is_ack:
								logger.error(f"[I8DP] Trame received is an ACK. Raw value: {data['data']}")
							else:
								logger.info(f"[I8DP] Received trame {{{i8dp_trame.seq}}}[{ '|'.join((['BEGIN'] if i8dp_trame.begin else []) + (['MF'] if i8dp_trame.more_frag else []) + (['TO_ACK'] if i8dp_trame.needs_ack else []))}]")
								if i8dp_trame.begin:
									if transmission_in_progress:
										logger.info("[I8DP] Ignored because transmission is already in progress.")
										ignore_trame = True
									else:
										logger.info("[I8DP] Beggining a transmission")
										transmission_in_progress = True
										expected_seq = i8dp_trame.seq
										fragment_burst = []
										chunks_to_write = []
										seq_ack_list = []
										should_end = False

										# this shouldn't happen ...
										if current_file is not None:
											current_file.close()
											remove(current_file.name)
										
										current_filename = tmp_dir + str(time_ns()) + '-' + data['from'].address.hex() + '-' + i8dp_trame.data.hex()[-8:] + ".bin"
										current_file = open(current_filename, 'wb')

								# To make things easy, if the first one is lost we ignore the rest
								# Because it could cause
								if not transmission_in_progress:
									logger.info("[I8DP] Ignored because no trame with BEGIN flag was received.")
									ignore_trame = True
								elif i8dp_trame.seq < expected_seq or (expected_seq in RANGE_0_BURST_MAX_LEN and i8dp_trame.seq in RANGE_LIMIT_BURST_MAX_LEN):
									logger.info(f"[I8DP] Ignored because sequence number is smaller than expected ({i8dp_trame.seq} < {expected_seq}).")
									ignore_trame = True
								#  elif (i8dp_trame.seq >= (expected_seq + I8DP_Trame.BURST_MAX_LEN)%I8DP_Trame.SequenceGenerator.LIMIT) !=   (i8dp_trame.seq <=  expected_seq - I8DP_Trame.BURST_MAX_LEN):
								#  	logger.info(f"[I8DP] Ignored because sequence number is not in burst ({i8dp_trame.seq} ]{expected_seq - I8DP_Trame.BURST_MAX_LEN},{expected_seq + I8DP_Trame.BURST_MAX_LEN}[).")
								#  	ignore_trame = True

								if not ignore_trame and i8dp_trame not in fragment_burst:
									bisect.insort(fragment_burst, i8dp_trame)
									# fragment_burst.append(i8dp_trame)
									seq_ack_list.append(i8dp_trame.seq)
								# seq_list = [frag.seq for frag in fragment_burst]  
								# logger.error(f"seq_list [before]: {seq_list}")
								if transmission_in_progress and i8dp_trame.needs_ack:
									# When it's a packet that needs ack we send it with all the previous ones
									logger.info(f"[I8DP] Trame {i8dp_trame.seq} needs ACK, sending it for {seq_ack_list}.")
									responses_trames_queue.put({'trame' : I8DP_Trame.ack_trame(i8dp_trame.seq, seq_ack_list), 'to' : data['from']})
									seq_ack_list = []

								while not ignore_trame and (fragment_burst and fragment_burst[0] == expected_seq):
									logger.info(f"[I8DP] Writing trame {fragment_burst[0].seq} data to temporary storage.")
									chunks_to_write.append(fragment_burst.pop(0).data)
									# seq_list.pop(0)
									expected_seq = (expected_seq + 1)%I8DP_Trame.SequenceGenerator.LIMIT
									
								logger.info(f"[I8DP] Next trame should be {expected_seq}.")
								logger.info(f"[I8DP] {[_.seq for _ in fragment_burst]} trames remain.")	
								if current_file is not None:
									current_file.write(b''.join(chunks_to_write))
									chunks_to_write = []
									# 	logger.error(f"seq_list [after ]: {seq_list}")
									

								
								if not i8dp_trame.more_frag:
									should_end = True

								if not ignore_trame and should_end and not fragment_burst:
									logger.info("[I8DP] Ending transmission.")
									if current_file is not None:
										current_file.close()
										current_file = None
	
									transmission_in_progress = False
									assembled_data_queue.put(current_filename)
					except ValueError:
						# Invalid protocolID, pass
						pass
				except queue.Empty:
					elapsed_time_without_trame += 1
					if elapsed_time_without_trame >= inactive_time_limit:
						logger.info(f"Thread timeout. Exiting until next message.")
						if current_file is not None:
							current_file.close()
						break


		def notify_trame(self,  trame : dict) -> None:
			sender = trame['from']
			with self._notify_lock:
				if sender not in self._threads or not self._threads[sender].is_alive():
					self._thread_trame_reception_queues[sender] = queue.Queue()
					self._thread_stop_events[sender] = threading.Event()
					self._threads[sender] = threading.Thread(target=DataReceiver.ReceiverThreadPool.__run, args=(self._tmp_dir, self._inactive_time_limit, self._thread_stop_events[sender], self._thread_trame_reception_queues[sender], self._assembled_data_queue, self._responses_trames_queue))
					self._threads[sender].name = f'Thread-{sender}'
					self._threads[sender].start()

				self._thread_trame_reception_queues[sender].put(trame)
			

		def stop(self):
			for an_event in self._thread_stop_events.values():
				an_event.set()

			for a_thread in self._threads.values():
				a_thread.join()

			self._ack_thread_stop_event.set()
			self._ack_thread.join()


	__slots__ = ('_process', '_device', '_queue', '_stop_event', 
		'_tmp_dir', '_logger', '_del_dir', '_thread_inactive_time_limit',
		'_log_dir')

	def __init__(self, 
		path                       : str  = '/dev/ttyUSB0',
		speed                      : int  = 230400,
		tmp_dir                    : str  = '/tmp/datareceiver',
		del_dir                    : bool = False,
		log_dir                    : str  = './log',
		self_stop                  : bool = False,
		thread_inactive_time_limit : int  = 600,
		base_log_level             : int  = logging.NOTSET):



		self._log_dir = log_dir + '/' 
		Path(self._log_dir).mkdir(parents=True, exist_ok=True)
		
		_prepare_logger(base_log_level, self._log_dir, 'datareceiver')

		self._tmp_dir = tmp_dir + '/' 
		Path(self._tmp_dir).mkdir(parents=True, exist_ok=True)

		self._del_dir = del_dir

		
		self._queue      : multiprocessing.Queue             = multiprocessing.Queue()
		self._stop_event : multiprocessing.synchronize.Event = multiprocessing.Event()
		
		if self_stop:
			atexit.register(self.stop)

		self._thread_inactive_time_limit = thread_inactive_time_limit
		self._process = multiprocessing.Process(target=self.__run, args=(path, speed))
		self._process.start()


	def _init_device(self,  path: str, speed: int):	
		self._device = XBeeDevice(path, speed)
		self._device.open()
		self._device.set_sync_ops_timeout(None)
		
		logger.info(f'Own device 16 bits address: {self._device.get_16bit_addr()}')
		logger.info(f'Own device 64 bits address: {self._device.get_64bit_addr()}')


	def stop(self) -> None:
		logger.info("Stopping DataReceiver process")
		self._stop_event.set()
		self._process.join()

	
	def __run(self, path : str, speed : int):	
		def __packet_received_callback(packet):
			if (packet.get_frame_type() in (ApiFrameType.RX_64, ApiFrameType.RX_16, ApiFrameType.RECEIVE_PACKET)) and hasattr(packet, 'rf_data') and hasattr(packet, 'x64bit_source_addr'):
				rssi = None
				if hasattr(packet, 'rssi'):
					rssi = packet.rssi
				pool.notify_trame({'from' : packet.x64bit_source_addr, 'data' : packet.rf_data, 'rssi' : rssi})
		
		if multiprocessing.parent_process() is None:
			logger.error("Tried to call run() method from main process.")
			return
		
		self._init_device(path=path, speed=speed)
		signal.signal(signal.SIGINT, signal.SIG_IGN)

		self._device.add_packet_received_callback(__packet_received_callback)

		logger.info("DataReceiver process created")

		pool = DataReceiver.ReceiverThreadPool(self._device, self._queue, self._tmp_dir, self._thread_inactive_time_limit)
		
		self._stop_event.wait()
		pool.stop()

		self._device.del_packet_received_callback(__packet_received_callback)
		logger.info("DataSender process exiting")
		
		if self._del_dir:
			logger.info("Removing temporary files")
			rmtree(self._tmp_dir, ignore_errors=True)

		self._device.close()


	def get_data_filename(self) -> str:
		return self._queue.get()
