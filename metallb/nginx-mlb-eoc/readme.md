running it
-----------
helm upgrade thib --install nginx-mlb-eoc/ -n ns-thib-system

the service that need to have the IP needs to be annotated
----------------------------------------------------------

oc annotate service/router-tektutor3-ingress metallb.universe.tf/ip-allocated-from-pool=192.168.22.180 -n openshift-ingress