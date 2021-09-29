#!/usr/bin/env bash




usage(){
	echo 'Usage: '${0}
	echo -e '\t -i --install: create the user and installs the program and service. [default]'
	echo -e '\t -d --delete:  deletes the user, program and service.'
	echo -e '\t -h --help:    print this message'
}


delete=false
#Get arguments into corresponding variables
while [[ $# -gt 0 ]]; do
	case ${1} in
		-d|--delete) # delete
			delete=true
			shift
			;;
		-i|--install) # install
			delete=false
			shift
			;;
		-h|--help) # help
			usage
			exit 0
	esac
	shift
done

if ${delete}; then
	sudo systemctl stop i8-forwarder.service
	sudo systemctl disable i8-forwarder.service
	sudo rm /etc/systemd/system/i8-forwarder.service

	sudo userdel -r i8utils
else
	sudo useradd -m i8utils
	sudo cp -r src/* /home/i8utils
	sudo cp i8-forwarder.service /etc/systemd/system/

	sudo systemctl enable i8-forwarder.service
	sudo systemctl start i8-forwarder.service
fi
