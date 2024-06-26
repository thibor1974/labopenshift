running it
-----------
helm upgrade thib --install nginx-mlb-eoc/ -n ns-thib-system

helm upgrade thib --install nginx-mlb-eoc/ -n ns-thib-system -f nginx-mlb-eoc/values-tektutor2.yaml


Sample for testing
toto.tektutor2.ocp.lan 192.168.22.182
toto.tektutor3.ocp.lan 192.168.22.183
toto.tektutor4.ocp.lan 192.168.22.184
toto.tektutor5.ocp.lan 192.168.22.185


the service that need to have the IP needs to be annotated
----------------------------------------------------------

oc annotate service/router-tektutor3-ingress metallb.universe.tf/ip-allocated-from-pool=192.168.22.180 -n openshift-ingress