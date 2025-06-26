#!/bin/bash
# dump into a result file all available operators
cat operator-catalog.txt | while read LINE
do 
	echo $LINE
	echo "-------------------------------------------"
       	oc-mirror list operators --catalog=registry.redhat.io/redhat/$LINE
       	echo "-------------------------------------------"
done  > results.txt
