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

import logging

from enum import Flag
from functools import total_ordering
from struct import pack, unpack
from typing import Final, List, Optional

from digi.xbee.devices import XBee64BitAddress, XBeeDevice
from digi.xbee.exception import TimeoutException, TransmitException

from econect.protocol import I8TL

'''
	I8DP : Datagram Protocol for IEEE 802.14.5
'''

i8dp_logger = logging.getLogger('I8DP')

@total_ordering
class I8DP_Trame:
	BURST_MAX_LEN   : int        =  8
	PAYLOAD_MAX_LEN : Final[int] = 85

	class IncompatibleOptionsException(Exception):
		def __init__(self, options : 'I8DP_Trame.I8DP_Flags'):
			self.message = "Selected options are incompatible ({})".format(options)
			super().__init__(self.message)

	class ExcededPayloadMaxLenException(Exception):
		def __init__(self, count : int):
			self.message = "Data should contain at most {} bytes (got {})".format(I8DP_Trame.PAYLOAD_MAX_LEN, count)
			super().__init__(self.message)

	class SequenceGenerator:
		LIMIT : int = 256
		
		__slots__  = ('__value')

		def __init__(self, value: int=255) -> None:
			self.__value = value
			#self.__lock = threading.Lock()

		def current(self) -> int:
			#with self.__lock:
			return self.__value

		
		def next(self) -> int:
			#with self.__lock:
			self.__value = (self.__value + 1)%I8DP_Trame.SequenceGenerator.LIMIT
			return self.__value


	class I8DP_Flags(Flag):
		I8DP_RST       = I8TL.Protocol_ID.I8DP.value + 0b1111
		I8DP_NONE      = I8TL.Protocol_ID.I8DP.value + 0b0000
		I8DP_BEGIN     = I8TL.Protocol_ID.I8DP.value + 0b1000
		I8DP_IS_ACK    = I8TL.Protocol_ID.I8DP.value + 0b0100
		I8DP_NEEDS_ACK = I8TL.Protocol_ID.I8DP.value + 0b0010
		I8DP_MORE_FRAG = I8TL.Protocol_ID.I8DP.value + 0b0001
		

		def is_set(self, other : 'I8DP_Trame.I8DP_Flags') -> bool:
			return (self & other) == other

	__slots__ = ('_options', '_seq', '_data', '_ackd_trames')

	__sequence : 'I8DP_Trame.SequenceGenerator' = SequenceGenerator()

	def __init__(self, options : 'I8DP_Trame.I8DP_Flags' = I8DP_Flags.I8DP_NONE, data: bytes = None, seq: int = None, ackd_trames : List[int] = []):
		self._options = options
		self._data = None
		self._seq = -1
		#An ACK Trame can't contain any other options

		if self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_IS_ACK|I8DP_Trame.I8DP_Flags.I8DP_MORE_FRAG) or self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_IS_ACK|I8DP_Trame.I8DP_Flags.I8DP_NEEDS_ACK) :
			raise I8DP_Trame.IncompatibleOptionsException(self._options)

		#If it's an ACK, you should provide a seq number to ack and a list of which trames in the sequences are ack.
		if self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_IS_ACK):
			if seq is None:
				raise ValueError("sequence number must be provided when building an ack trame.")
			if len(ackd_trames) > I8DP_Trame.PAYLOAD_MAX_LEN:
				raise I8DP_Trame.ExcededPayloadMaxLenException(len(ackd_trames))
			
			self._seq = seq
			self._ackd_trames = ackd_trames			
		else:
			#if it's not an ACK data must be provided and containe less elements than I8DP_Trame.PAYLOAD_MAX_LEN
			if data is None:
				raise ValueError("data must be provided when it is a data packet (I8DP_IS_ACK flag is not set in options)")
			if len(data) > I8DP_Trame.PAYLOAD_MAX_LEN:
				raise I8DP_Trame.ExcededPayloadMaxLenException(len(data))

			#if you provide a sequence number, it's useless it's automaticaly generated
			if seq is not None:
				#TODO: Warning about non usage
				pass

			self._seq = I8DP_Trame.__sequence.next()
			self._data = data
		



	def __eq__(self, other : object) -> bool:
		if isinstance(other, I8DP_Trame):
			return  self._seq == other._seq #and self._data == other._data
		if isinstance(other, int):
			return self._seq == other
		return NotImplemented

	def __lt__(self, other : object) -> bool:
		if isinstance(other, I8DP_Trame):
			return  self._seq < other._seq 
		if isinstance(other, int):
			return self._seq < other
		return NotImplemented

	def __hash__(self) -> int:
		return hash(self._seq)

	def __repr__(self) -> str:
		return self.__str__()

	def __str__(self) -> str:
		return str(self._seq)
	@property
	def data(self) -> bytes:
		if self._data is not None:
			return self._data
		return bytes()
		
	@property
	def seq(self) -> int:
		return self._seq


	@property
	def begin(self):
		return self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_BEGIN)
	

	@property
	def is_rst(self):
		return self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_RST) and self._seq == (I8DP_Trame.SequenceGenerator.LIMIT - 1)
	
	@property
	def is_ack(self) -> bool:
		return self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_IS_ACK)

	@property
	def needs_ack(self) -> bool:
		return self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_NEEDS_ACK)


	@property
	def more_frag(self):
		return self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_MORE_FRAG)
	
	@property
	def ack_list(self):
		return ([self._seq] if self.is_ack else []) + [*self._ackd_trames]
		

	def unset_begin(self) -> None:
		self._options = self._options & ~I8DP_Trame.I8DP_Flags.I8DP_BEGIN

	def set_needs_ack(self) -> None:
		self._options = self._options | I8DP_Trame.I8DP_Flags.I8DP_NEEDS_ACK


	def to_bytes(self) -> bytes:
		res_byte_array = pack('BB', self._options.value, self._seq) 
		if not self._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_IS_ACK):
			if self._data is not None:
				res_byte_array += self._data
		else:
			for ack_seq in self._ackd_trames:
				res_byte_array += pack('B', ack_seq)
	
		return res_byte_array

	@staticmethod
	def from_bytes(byte_array : bytes) -> 'I8DP_Trame':
		i8dp_trame = I8DP_Trame.__new__(I8DP_Trame)
		i8dp_trame._options = I8DP_Trame.I8DP_Flags(byte_array[0])
		i8dp_trame._seq = unpack('B', byte_array[1:2])[0]
		i8dp_trame._data = None
		if not i8dp_trame._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_RST):
			if not i8dp_trame._options.is_set(I8DP_Trame.I8DP_Flags.I8DP_IS_ACK):
				i8dp_trame._data = byte_array[2:]
			else:
				i8dp_trame._ackd_trames = []
				for ack_seq in byte_array[2:]:
					i8dp_trame._ackd_trames.append(unpack('B', bytes([ack_seq]))[0])

		return i8dp_trame


	@staticmethod
	def rst_trame() -> 'I8DP_Trame':
		rst_trame = I8DP_Trame.__new__(I8DP_Trame)
		
		rst_trame._options = I8DP_Trame.I8DP_Flags.I8DP_RST
		rst_trame._seq = I8DP_Trame.SequenceGenerator.LIMIT - 1
		
		rst_trame._ackd_trames = []
		rst_trame._data = None

		return rst_trame



	


def i8dp_build_data_trame(data : bytes, begin : bool = True, need_ack : bool = True, more_fragments : bool = False) -> I8DP_Trame:
	options = I8DP_Trame.I8DP_Flags.I8DP_NONE
	if need_ack:
		options |= I8DP_Trame.I8DP_Flags.I8DP_NEEDS_ACK
	if more_fragments:
		options |= I8DP_Trame.I8DP_Flags.I8DP_MORE_FRAG
	if begin:
		options |= I8DP_Trame.I8DP_Flags.I8DP_BEGIN
	return I8DP_Trame(options, data)


def i8dp_send_trame(device : XBeeDevice, destination_addr : XBee64BitAddress, i8dp_trame : I8DP_Trame, timeout : int = 3) -> Optional[I8DP_Trame]:
	ack_received = False
	try:
		I8TL.i8tl_send_trame(device, destination_addr, i8dp_trame.to_bytes(), i8dp_logger)
		if i8dp_trame.needs_ack:
			try:
				raw_response = device.read_data(timeout)
				if raw_response is not None and (raw_response.data[0] & I8TL.Protocol_ID.I8DP.value) == I8TL.Protocol_ID.I8DP.value:				
					i8dp_ack = I8DP_Trame.from_bytes(raw_response.data)
					ack_received = ((i8dp_trame.seq == i8dp_ack.seq) and i8dp_ack.is_ack)		
			except TimeoutException:
				i8dp_logger.warning("TimeoutException")

			if ack_received:
				return i8dp_ack
	
	except TransmitException:
		i8dp_logger.warning("TransmitException")

	return None

def i8dp_build_ack_trame(seq : int, ackd_trames : List[int]) -> I8DP_Trame:
	return I8DP_Trame(I8DP_Trame.I8DP_Flags.I8DP_IS_ACK, seq=seq, ackd_trames=ackd_trames)
