#!/usr/bin/env python3

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

import mmap
import os
from pathlib import Path
from sys import argv
from typing import cast

from config import RECEIVED_DIR
from econect.formats import F8Wrapper, NeoCayenneLPP
from econect.protocol.I8TL import DataReceiver


def ensure_dir_exists(dir_name : str):
		Path(dir_name).mkdir(parents=True, exist_ok=True)

def handle_neocayenne(neocayenne_trame : NeoCayenneLPP):
	pass



def handle_f8wrapper(filename : str, data : bytes):
	ensure_dir_exists(RECEIVED_DIR)
	with open('/'.join([RECEIVED_DIR, filename]), 'wb') as f:
		f.write(data)
	
	print(f'Saved {filename} file')


if __name__ == '__main__':
	devfile : str = "/dev/ttyUSB1"
	bauds   : int = 230400

	broker  : str = ""
	port    : int = 0

	
	if len(argv) > 1:
		devfile = argv[1]
	if len(argv) > 2:
		file_to_send = argv[2]
	
	dr : DataReceiver = DataReceiver(path=devfile, speed=bauds, self_stop=True, del_dir=True, thread_inactive_time_limit=10)
	
	try:
		while True:
			filename = dr.get_data_filename()
			with open(filename, 'rb') as file:
				with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as mm:
					if mm[0] in [version.value for version in NeoCayenneLPP.Version]:
						neocayenne_trame = mm
						handle_neocayenne(NeoCayenneLPP.from_bytes(cast(bytes,neocayenne_trame)))
						print("Got NeoCayenneLPP data")
					elif mm[0] == F8Wrapper.PREAMBLE:
						f8_filename = mm[2: 2 + mm[1]].decode('utf-8')
						f8_data = mm[2 + mm[1]:]

						print(f"Got F8Wrapper data ({f8_filename})")
						handle_f8wrapper(f8_filename, f8_data)
			os.remove(filename)
	except KeyboardInterrupt:
		exit(0)
