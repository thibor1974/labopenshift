#!/bin/sh
for node in $(oc get nodes -o jsonpath='{.items[*].metadata.name}')
do 
	oc debug node/${node} -- chroot /host shutdown -h 1
done
