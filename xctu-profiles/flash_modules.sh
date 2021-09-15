#!/usr/bin/env bash


usage(){
	echo 'Usage: '${0}' -p <profile> [-f <module serial port> (default /dev/ttyUSB0)] [-s <speed|"slow"|"fast" (default: "fast")]'
}


#Get arguments into corresponding variables
while [[ $# -gt 0 ]]; do
	case ${1} in
		-p) # profile
			profile="${2}"
			shift 
			;;
		-f) # serial port
			devfile="${2}"
			shift
			;;
		-s) # speed
			speed="${2}"
			shift
			;;
		-h|--help) #help
			usage
			exit 0
	esac
	shift
done


if [ -z ${profile} ] || [ ! -f ${profile} ]
then
	echo "Error: A profile to flash must be given."
	echo ""

	usage
	exit 1
fi


devfile=${devfile:-/dev/ttyUSB0}
if [ ! -c ${devfile} ]
then
	echo "Error: The provided serial port doest not exist or is not a serial port."
	echo ""

	usage
	exit 1
fi


speed=${speed:-230400}
if   [ ${speed} == "fast" ]
then
	speed=230400
elif [ ${speed} == "slow" ]
then
	speed=9600
elif ! test "${speed}" -gt 0 2> /dev/null ;
then
	echo 'Error: The provided speed is not a positive integer neither the "fast" nor "slow" string.'
	echo ""

	usage
	exit 1
fi


XCTUcmd load_profile -f ${profile} -p ${devfile} -b ${speed} -v