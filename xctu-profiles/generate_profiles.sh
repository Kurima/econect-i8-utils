#!/usr/bin/env bash

#The key is 16 random bytes and is generated
#if not found
if [ ! -f aes.key ]; then
	openssl rand 16 > aes.key
fi


key=$(hexdump -ve '1/1 "%.2x"' aes.key)
for profile in ${@};
do
	# The profiles are .zip files (renamed .xpro) containing a profile.xml with the key info
	# The profile.xml is extracted, edited with the key value and reziped
	unzip -p ${profile} profile.xml | xmlstarlet ed -P -u "data/profile/settings/setting[@command='KY']" -v ${key} > profile.xml
	zip ${profile} profile.xml
	rm profile.xml
done;

