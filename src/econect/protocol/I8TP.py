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

import time
from enum import Flag
from struct import pack
from typing import Final, Optional, Tuple

from digi.xbee.devices import XBee64BitAddress, XBeeDevice
from digi.xbee.exception import TimeoutException

from econect.protocol import I8TL

'''
	I8TP : Time Protocol for IEEE 802.14.5
'''




i8tp_logger = logging.getLogger('I8TP')

class I8TP_Trame:

	class I8TP_Type(Flag):
		I8TP_TIME_REQ =  I8TL.Protocol_ID.I8TP.value + 0b0000
		I8TP_TIME_RES =  I8TL.Protocol_ID.I8TP.value + 0b0001 
		
		def is_set(self, other : 'I8TP_Trame.I8TP_Type') -> bool:
			return (self & other) == other

	__slots__ = ('_options', '_time')

	
	def __init__(self, options: I8TP_Type=I8TP_Type.I8TP_TIME_REQ) -> None:
		self._options = options
		self._time = None
		if self.is_res:
			self._time = time.time_ns().to_bytes(8, 'big')



	def __eq__(self, other : object) -> bool :
		if not isinstance(other, I8TP_Trame):
			return NotImplemented
		return self._options.value == other._options.value and self._time == other._time

	@property
	def time(self) -> Optional[int]:
		if not self.is_res or self._time is None:
			return None
		return int.from_bytes(self._time, 'big')


	@property
	def is_req(self) -> bool:
		return self._options.is_set(I8TP_Trame.I8TP_Type.I8TP_TIME_REQ)

	@property
	def is_res(self) -> bool:
		return self._options.is_set(I8TP_Trame.I8TP_Type.I8TP_TIME_RES)
	

	def to_bytes(self) -> bytes:
		res_byte_array = pack('B', self._options.value) 
		if  self.is_res and self._time is not None:
			res_byte_array += self._time
	
		return res_byte_array

	@staticmethod
	def from_bytes(byte_array : bytes) -> 'I8TP_Trame':
		i8tp_trame = I8TP_Trame.__new__(I8TP_Trame)
		i8tp_trame._options = I8TP_Trame.I8TP_Type(byte_array[0])


		if  i8tp_trame.is_res:
			i8tp_trame._time = byte_array[1:]

		return i8tp_trame




def __set_time_on_linux(time_ns : int) -> bool:
	'''
	A method to set system clock at a given `time_ns` value on Linux,
	using librt's clock_settime.

	WARNING: root access is needed in order to set the clock. 
	'''
	import ctypes
	import ctypes.util

	CLOCK_REALTIME : Final[int] = 0

	class timespec(ctypes.Structure):
		_fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]

	librt = ctypes.CDLL(ctypes.util.find_library("rt"))
	
	ts = timespec()
	ts.tv_sec = int(time_ns*10e-9)
	ts.tv_nsec = int(time_ns - ts.tv_sec*10e9)

	return librt.clock_settime(CLOCK_REALTIME, ctypes.byref(ts)) == 0



def i8tp_request(device :XBeeDevice, destination_addr : XBee64BitAddress, retries : int = 3, timeout : int = 3) -> Tuple[int,int]:
	server_time = -1
	rtt = -1
	i8tp_request = I8TP_Trame().to_bytes()

	while server_time == -1 and retries > 0:
		
		time_before_send = time.time_ns()
		I8TL.i8tl_send_trame(device, destination_addr, i8tp_request, i8tp_logger)
		try:
			raw_response = device.read_data(timeout)
			time_after_send = time.time_ns()
			if raw_response is not None and (raw_response.data[0] & 0xF0) == I8TL.Protocol_ID.I8TP.value:	
				i8tp_response = I8TP_Trame.from_bytes(raw_response.data)
				if i8tp_response.time:
					server_time = i8tp_response.time 
				rtt = time_after_send - time_before_send

		except TimeoutException:
			pass
		retries-=1


	return server_time, rtt

def i8tp_request_delta(device : XBeeDevice, destination_addr : XBee64BitAddress, retries : int = 3, timeout : int = 3) -> int:
	server_time, rtt = i8tp_request(device, destination_addr, retries=retries, timeout=timeout)
	#Should be rtt*0.5 but RTT is not symetrical, we spend more time on the server side, hence the higher coef.
	return round(server_time + rtt*0.65) - time.time_ns()


def i8tp_build_response() -> I8TP_Trame:
	return I8TP_Trame(I8TP_Trame.I8TP_Type.I8TP_TIME_RES)

def i8tp_response(device : XBeeDevice, destination_addr : XBee64BitAddress) -> None:
	'''
	Generate a response for its own time using the device `device` to communicate
	to `destination_addr`.
	'''
	I8TL.i8tl_send_trame(device, destination_addr, I8TP_Trame(I8TP_Trame.I8TP_Type.I8TP_TIME_RES).to_bytes(), i8tp_logger)
