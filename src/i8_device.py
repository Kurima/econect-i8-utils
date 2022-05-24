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


from sys import argv, exit
from time import sleep
from typing import Final

from config import EXAMPLES_DIR, EXAMPLES_FILES, LOG_DIR
from econect.formats import NeoCayenneLPP
from econect.protocol.I8TL import DataSender

TEMPERATURE_SENSOR_ID : Final[int] = -5
WEIGHT_SENSOR_ID      : Final[int] = -10 

def get_temperature() -> float:
	import random
	return random.uniform(-11.75,51.75)

def get_weight() -> int:
	import random
	return round(random.uniform(0, 65535))



if __name__ == "__main__":
	devfile : str = "/dev/ttyUSB0"
	bauds   : int = 230400

	
	if len(argv) > 1:
		devfile = argv[1]
	if len(argv) > 2:
		file_to_send = argv[2]
	
	ds : DataSender = DataSender(path=devfile, speed=bauds, del_dir=True, self_stop=False, qos_info=True, log_dir=LOG_DIR, response_timeout=1, retries=3)
	
	# try:
	# 	i : int = 0
	# 	while True:
	# 		# data = NeoCayenneLPP()
	# 		# data.add_temperature(TEMPERATURE_SENSOR_ID, get_temperature())
	# 		# data.add_weight(WEIGHT_SENSOR_ID, get_weight())
	# 		# ds.notify_data_to_send(data.to_bytes())
		
	# 		# i = i + 1
	# 		# sleep(2)
	# 		# if i == 10:
	# 		# 	exit(0)
			
	# 		ds.notify_file_to_send(EXAMPLES_DIR + EXAMPLES_FILES[i])
	# 		i = (i+1)%len(EXAMPLES_FILES)
			
	# 		sleep(1)
	# except KeyboardInterrupt:
	# 	exit(0)

	try:
		for e in EXAMPLES_FILES:
			ds.notify_file_to_send(EXAMPLES_DIR + e)
	
		while ds.is_sending():
			sleep(1)

	except KeyboardInterrupt:
		pass
	finally:		
		ds.stop()
