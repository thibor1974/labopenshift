export NAME=nginx-7c989c75f5-rgcpr
export NAMESPACE=petbattle
export pod_id=$(chroot /host crictl pods --namespace ${NAMESPACE} --name ${NAME} -q)
export ns_path="/host$(chroot /host bash -c "crictl inspectp $pod_id | jq '.info.runtimeSpec.linux.namespaces[]|select(.type==\"network\").path' -r")"
export nsenter_parameters="--net=${ns_path}"


Determine interface

sh-5.1# nsenter $nsenter_parameters -- chroot /host ip a
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host 
       valid_lft forever preferred_lft forever
2: eth0@if21: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1400 qdisc noqueue state UP group default 
    link/ether 0a:58:0a:80:02:0d brd ff:ff:ff:ff:ff:ff link-netns ea133302-dfe9-43a7-9cf2-50e7b3cbe35e
    inet 10.128.2.13/23 brd 10.128.3.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::858:aff:fe80:20d/64 scope link 
       valid_lft forever preferred_lft forever

INTERFACE=eth0
nsenter $nsenter_parameters -- tcpdump -nn -i ${INTERFACE} -w /host/var/tmp/${HOSTNAME}_$(date +\%d_%m_%Y-%H_%M_%S-%Z).pcap # ${TCPDUMP_EXTRA_PARAMS}