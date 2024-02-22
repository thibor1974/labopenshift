#!/bin/bash
# script to pring version for each operator being used
# create an ouput to a date file 
responsefile=$1
osh_version=$2
file=$3
cat ${responsefile} | while read catalog package channel
do 
	version=$(oc-mirror list operators --catalog=registry.redhat.io/redhat/${catalog}:${osh_version} --package=${package} --channel=${channel})
	echo ${catalog}:${osh_version} ${package} ${channel} ${version} >> ${file}
done
