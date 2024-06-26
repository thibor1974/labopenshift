Todo List
----------
- label for sharding
- nodeport removal for router-tektutor2-ingress
- annotation of service router-tektutor2-ingress how to avoid 




running it
-----------
helm upgrade thib --install nginx-mlb-eoc/ -n ns-thib-system

Sample for testing
toto.tektutor2.ocp.lan 192.168.22.182
toto.tektutor3.ocp.lan 192.168.22.183
toto.tektutor4.ocp.lan 192.168.22.184
toto.tektutor5.ocp.lan 192.168.22.185


the service that need to have the IP needs to be annotated
----------------------------------------------------------
helm upgrade thib2 --install nginx-mlb-eoc/ -n ns-thib-system -f nginx-mlb-eoc/values-tektutor2.yaml
oc annotate service/router-tektutor2-ingress metallb.universe.tf/address-pool=pool1 -n openshift-ingress
oc annotate service/router-tektutor2-ingress metallb.universe.tf/loadBalancerIPs=192.168.22.182 -n openshift-ingress

helm upgrade thib3 --install nginx-mlb-eoc/ -n ns-thib-system -f nginx-mlb-eoc/values-tektutor3.yaml
oc annotate service/router-tektutor3-ingress metallb.universe.tf/address-pool=pool1 -n openshift-ingress # Not needed ???
oc annotate service/router-tektutor3-ingress metallb.universe.tf/loadBalancerIPs=192.168.22.183 -n openshift-ingress



Label thing for the sharding
-----------------------------

https://access.redhat.com/solutions/5097511

oc edit  ingresscontrollers.operator.openshift.io  default -n openshift-ingress-operator

  namespaceSelector:
    matchExpressions:
    - key: type
      operator: NotIn
      values:
      - tektutor2
      - tektutor3
      - tektutor4
      - tektutor5