#!/usr/bin/python
#coding: utf-8 -*-

# (c) 2013, Benno Joy <benno@ansible.com>
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

try:
    try:
        from neutronclient.neutron import client
    except ImportError:
        from quantumclient.quantum import client
    from keystoneclient.v2_0 import client as ksclient
except ImportError:
    print("failed=True msg='quantumclient (or neutronclient) and keystone client are required'")
DOCUMENTATION = '''
---
module: quantum_router_gateway
version_added: "1.2"
short_description: set/unset a gateway interface for the router with the specified external network
description:
   - Creates/Removes a gateway interface from the router, used to associate a external network with a router to route external traffic.
options:
   login_username:
     description:
        - login username to authenticate to keystone
     required: true
     default: admin
   login_password:
     description:
        - Password of login user
     required: true
     default: 'yes'
   login_tenant_name:
     description:
        - The tenant name of the login user
     required: true
     default: 'yes'
   auth_url:
     description:
        - The keystone URL for authentication
     required: false
     default: 'http://127.0.0.1:35357/v2.0/'
   region_name:
     description:
        - Name of the region
     required: false
     default: None
   state:
     description:
        - Indicate desired state of the resource
     choices: ['present', 'absent']
     default: present
   router_name:
     description:
        - Name of the router to which the gateway should be attached.
     required: true
     default: None
   network_name:
     description:
        - Name of the external network which should be attached to the router.
     required: true
     default: None
requirements: ["quantumclient", "neutronclient", "keystoneclient"]
'''

EXAMPLES = '''
# Attach an external network with a router to allow flow of external traffic
- quantum_router_gateway: state=present login_username=admin login_password=admin
                          login_tenant_name=admin router_name=external_router
                          network_name=external_network
'''

_os_keystone = None
def _get_ksclient(module, kwargs):
    try:
        kclient = ksclient.Client(username=kwargs.get('login_username'),
                                 password=kwargs.get('login_password'),
                                 tenant_name=kwargs.get('login_tenant_name'),
                                 auth_url=kwargs.get('auth_url'))
    except Exception, e:
        module.fail_json(msg = "Error authenticating to the keystone: %s " % e.message)
    global _os_keystone
    _os_keystone = kclient
    return kclient


def _get_endpoint(module, ksclient):
    try:
        endpoint = ksclient.service_catalog.url_for(service_type='network', endpoint_type='publicURL')
    except Exception, e:
        module.fail_json(msg = "Error getting network endpoint: %s" % e.message)
    return endpoint

def _get_neutron_client(module, kwargs):
    _ksclient = _get_ksclient(module, kwargs)
    token = _ksclient.auth_token
    endpoint = _get_endpoint(module, _ksclient)
    kwargs = {
            'token': token,
            'endpoint_url': endpoint
    }
    try:
        neutron = client.Client('2.0', **kwargs)
    except Exception, e:
        module.fail_json(msg = "Error in connecting to neutron: %s " % e.message)
    return neutron

def _get_router_id(module, neutron):
    kwargs = {
            'name': module.params['router_name'],
    }
    try:
        routers = neutron.list_routers(**kwargs)
    except Exception, e:
        module.fail_json(msg = "Error in getting the router list: %s " % e.message)
    if not routers['routers']:
            return None
    return routers['routers'][0]['id']

def _get_net_id(neutron, module):
    kwargs = {
        'name':            module.params['network_name'],
        'router:external': True
    }
    try:
        networks = neutron.list_networks(**kwargs)
    except Exception, e:
        module.fail_json("Error in listing neutron networks: %s" % e.message)
    if not networks['networks']:
        return None
    return networks['networks'][0]['id']

def _get_port_id(neutron, module, router_id, network_id):
    kwargs = {
        'device_id': router_id,
        'network_id': network_id,
    }
    try:
        ports = neutron.list_ports(**kwargs)
    except Exception, e:
        module.fail_json( msg = "Error in listing ports: %s" % e.message)
    if not ports['ports']:
        return None
    return ports['ports'][0]['id']

def _add_gateway_router(neutron, module, router_id, network_id):
    kwargs = {
        'network_id': network_id
    }
    try:
        neutron.add_gateway_router(router_id, kwargs)
    except Exception, e:
        module.fail_json(msg = "Error in adding gateway to router: %s" % e.message)
    return True

def  _remove_gateway_router(neutron, module, router_id):
    try:
        neutron.remove_gateway_router(router_id)
    except Exception, e:
        module.fail_json(msg = "Error in removing gateway to router: %s" % e.message)
    return True

def main():

    argument_spec = openstack_argument_spec()
    argument_spec.update(dict(
            router_name        = dict(required=True),
            network_name       = dict(required=True),
            state              = dict(default='present', choices=['absent', 'present']),
    ))
    module = AnsibleModule(argument_spec=argument_spec)

    neutron = _get_neutron_client(module, module.params)
    router_id = _get_router_id(module, neutron)

    if not router_id:
        module.fail_json(msg="failed to get the router id, please check the router name")

    network_id = _get_net_id(neutron, module)
    if not network_id:
        module.fail_json(msg="failed to get the network id, please check the network name and make sure it is external")

    if module.params['state'] == 'present':
        port_id = _get_port_id(neutron, module, router_id, network_id)
        if not port_id:
            _add_gateway_router(neutron, module, router_id, network_id)
            module.exit_json(changed=True, result="created")
        module.exit_json(changed=False, result="success")

    if module.params['state'] == 'absent':
        port_id = _get_port_id(neutron, module, router_id, network_id)
        if not port_id:
            module.exit_json(changed=False, result="Success")
        _remove_gateway_router(neutron, module, router_id)
        module.exit_json(changed=True, result="Deleted")

# this is magic, see lib/ansible/module.params['common.py
from ansible.module_utils.basic import *
from ansible.module_utils.openstack import *
main()

