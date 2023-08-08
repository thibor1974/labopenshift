#!/bin/bash
# script to pring version for each operator being used
# create an ouput to a date file 
responsefile=$1
osh_version=$2
cat ${responsefile} | while read catalog packagfe channel
do 
	version=$(oc-mirror list operators --catalog=registry.redhat.io/redhat/${catalog}:${osh_version} --package=${package} --channel=${channel})
	echo ${version}
done
