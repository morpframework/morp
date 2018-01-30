import nose
import morepath
from webtest import TestApp as Client
from morp.authmanager.app import App
from morp.authmanager import create_app
from morp.authmanager.authpolicy import JWTWithAPIKeyIdentityPolicy
from morp.authmanager.model.user import UserCollection, UserSchema, GroupSchema
from more.jwtauth import JWTIdentityPolicy
import json
import yaml
import os
import copy
from more.basicauth import BasicAuthIdentityPolicy
import time
import transaction


def get_client(app, config='settings.yml', **kwargs):
    if isinstance(config, str):
        with open(os.path.join(os.path.dirname(__file__), config)) as f:
            settings = yaml.load(f)
    else:
        settings = config

    def get_identity_policy():
        return JWTWithAPIKeyIdentityPolicy(master_secret='secret', leeway=10,
                                           allow_refresh=True)

    def verify_identity(identity):
        return True

    kwargs = {}
    appobj = create_app(app, settings, get_identity_policy=get_identity_policy,
                        verify_identity=verify_identity, **kwargs)
    request = appobj.request_class(
        app=appobj, environ={'PATH_INFO': '/'})

    username = 'admin'
    password = 'password'
    transaction.manager.begin()
    context = UserCollection(
        request, appobj.get_authmanager_storage(request, UserSchema))
    userobj = context.create({'username': username,
                              'password': password,
                              'state': 'active'})
    gstorage = appobj.get_authmanager_storage(
        request, GroupSchema)
    group = gstorage.get('__default__')
    group.add_members([username])
    group.grant_member_role(username, 'administrator')
    transaction.commit()
    c = Client(appobj)
    return c


def login(c, username, password='password'):

    r = c.post_json('/api/v1/user/+login', {
        'username': username,
        'password': password
    })

    assert r.status_code == 200

    token = r.headers.get('Authorization').split()[1]

    c.authorization = ('JWT', token)

    return r.json


def logout(c):
    c.authorization = None


def _test_authentication(c):
    r = c.get('/api/v1/user/+login')

    # test schema access

    assert r.json['schema']['title'] == 'credential'

    ll = r.json['links'][0]
    assert ll['rel'] == 'login'
    assert ll['type'] == 'POST'

    r = c.post_json(ll['href'], {
        'username': 'admin',
        'password': 'password'
    })

    assert r.json == {
        'status': 'success'
    }

    logout(c)

    # test wrong login
    r = c.post_json('/api/v1/user/+login', {
        'username': 'invaliduser',
        'password': 'invalidpassword'
    }, expect_errors=True)

    assert r.json == {
        'status': 'error',
        'error': {
            'code': 401,
            'message': 'Invalid Username / Password'
        }
    }

    r = c.post_json('/api/v1/user/+login', {
        'username': 'admin',
        'password': 'invalidpassword'
    }, expect_errors=True)

    assert r.json == {
        'status': 'error',
        'error': {
            'code': 401,
            'message': 'Invalid Username / Password'
        }
    }

    # from now on we login as admin

    login(c, 'admin')

    # test refreshing token
    time.sleep(2)

    r = c.get('/api/v1/user/+refresh_token')

    n = r.headers.get('Authorization').split()

    assert c.authorization[1] != n[1]

    c.authorization = ('JWT', n[1])

    r = c.get('/api/v1/user/admin')

    assert r.json['data']['username'] == 'admin'
    assert r.json['data']['groups'] == ['__default__']
    assert r.json['data']['state'] == 'active'

    # query for nonexistent user

    r = c.get('/api/v1/user/unknownuser', expect_errors=True)

    assert r.status_code == 404

    r = c.get('/api/v1/user/')

    assert r.json['schema']['title'] == 'user'

    logout(c)

    # register new user, you shouldnt be allowed to if not logged in
    # as admin

    r = c.post_json('/api/v1/user/+register',
                    {'username': 'user1',
                     'password': 'password',
                     'password_validate': 'password'}, expect_errors=True)

    assert r.status_code == 403

    # register new user

    login(c, 'admin')

    r = c.post_json('/api/v1/user/+register',
                    {'username': 'user1',
                     'password': 'password',
                     'password_validate': 'password'}, expect_errors=True)

    assert r.json == {'status': 'success'}

    r = c.post_json('/api/v1/user/+register',
                    {'username': 'user2',
                     'password': 'password',
                     'password_validate': 'password'})

    assert r.json == {'status': 'success'}

    # fail if password is not string
    r = c.post_json('/api/v1/user/+register',
                    {'username': 'user3',
                     'password': {'hello': 'world'}},
                    expect_errors=True)

    assert r.status_code == 422

    # fail if duplicate user

    r = c.post_json('/api/v1/user/+register',
                    {'username': 'user1',
                     'password': 'password',
                     'password_validate': 'password'},
                    expect_errors=True)

    assert r.status_code == 422
    assert r.json['status'] == 'error'
    assert r.json['type'] == 'UserExistsError'

    r = c.get('/api/v1/user/user1')

    assert r.json['data']['username'] == 'user1'
    assert r.json['data']['groups'] == ['__default__']
    assert r.json['data']['state'] == 'active'
    assert 'password' not in r.json['data'].keys()

    # attempt to login as user1
    login(c, 'user1')

    login(c, 'admin')
    r = c.post_json(
        '/api/v1/user/user1/+statemachine', {'transition': 'deactivate'})

    r = c.get('/api/v1/user/user1')

    assert r.json['data']['username'] == 'user1'
    assert r.json['data']['groups'] == ['__default__']
    assert r.json['data']['state'] == 'inactive'

    r = c.post_json('/api/v1/user/+login', {
        'username': 'user1',
        'password': 'password'
    }, expect_errors=True)

    assert r.status_code == 401

    r = c.post_json(
        '/api/v1/user/user1/+statemachine', {'transition': 'activate'})

    login(c, 'user1')

    # reject setting password through the update API

    r = c.post_json('/api/v1/user/user1/',
                    {'password': 'newpass'}, expect_errors=True)

    assert r.status_code == 422

    r = c.post_json('/api/v1/user/user1/',
                    {'username': 'newusername'}, expect_errors=True)

    assert r.status_code == 422

    login(c, 'admin')

    # admin should be allowed to set password without requiring current password
    r = c.post_json('/api/v1/user/user1/+change_password', {
        'new_password': 'newpass',
        'new_password_validate': 'newpass'
    })

    assert r.status_code == 200

    login(c, 'user1', 'newpass')

    # user require current password
    r = c.post_json('/api/v1/user/user1/+change_password', {
        'new_password': 'password',
        'new_password_validate': 'password'
    }, expect_errors=True)

    assert r.status_code == 422

    # user require current password
    r = c.post_json('/api/v1/user/user1/+change_password', {
        'password': 'newpass',
        'new_password': 'password',
        'new_password_validate': 'password'
    }, expect_errors=True)

    assert r.status_code == 200

    login(c, 'admin')

    # api keys
    r = c.post_json('/api/v1/apikey/',
                    {'label': 'samplekey', 'password': 'password'})

    key_identity = r.json['data']['api_identity']
    key_secret = r.json['data']['api_secret']
    key_uuid = r.json['data']['uuid']
    assert len(key_identity) == 32
    assert len(key_secret) == 32
    assert r.json['data']['username'] == 'admin'

    r = c.get('/api/v1/apikey/%s' % key_uuid)

    assert key_identity == r.json['data']['api_identity']
    assert key_secret == r.json['data']['api_secret']
    assert key_uuid == r.json['data']['uuid']

    # user1 shouldnt see admin's apikey

    login(c, 'user1')

    r = c.get('/api/v1/apikey/+search')

    assert len(r.json['results']) == 0

    logout(c)

    # lets try deactivating user1 using API key
    r = c.post_json(
        '/api/v1/user/user1/+statemachine', {'transition': 'deactivate'},
        expect_errors=True)

    assert r.status_code == 403

    r = c.post_json(
        '/api/v1/user/user1/+statemachine',
        {'transition': 'deactivate'}, headers=[
            ('X-API-KEY', '.'.join([key_identity, key_secret]))
        ])

    assert r.status_code == 200

    login(c, 'admin')

    r = c.get('/api/v1/group/')

    assert r.json['schema']['title'] == 'group'

    r = c.post_json('/api/v1/group/', {'groupname': 'group1'})

    assert r.json['data']['groupname'] == 'group1'

    r = c.post_json('/api/v1/group/', {'groupname': 'group1'},
                    expect_errors=True)

    assert r.json['status'] == 'error'
    assert r.json['type'] == 'GroupExistsError'

    r = c.get('/api/v1/group/group1')

    assert r.json['data']['groupname'] == 'group1'

    r = c.post_json('/api/v1/group/group1/+grant',
                    {'mapping': {'user1': ['member']}})

    assert r.json == {'status': 'success'}

    r = c.post_json('/api/v1/group/group1/+grant',
                    {'mapping': {'dummyuser': ['member']}},
                    expect_errors=True)

    assert r.status_code == 422

    r = c.get('/api/v1/user/user1')

    assert list(sorted(r.json['data']['groups'])) == [
        '__default__', 'group1']

    r = c.get('/api/v1/group/group1/+members')

    assert r.json == {
        'users': [
            {'username': 'user1',
             'links': [{
                 'rel': 'self',
                 'type': 'GET',
                 'href': 'http://localhost/api/v1/user/user1'}],
             'roles': ['member']}]
    }

    r = c.post_json('/api/v1/group/group1/+grant', {'mapping': {
        'user1': ['manager']
    }})

    assert r.json == {'status': 'success'}

    r = c.get('/api/v1/group/group1/+members')

    assert r.json['users'][0]['roles'] == ['member', 'manager']

    r = c.post_json('/api/v1/group/group1/+grant', {'mapping': {
        'user1': ['editor']
    }})

    assert r.json == {'status': 'success'}

    r = c.get('/api/v1/group/group1/+members')

    assert sorted(r.json['users'][0]['roles']
                  ) == sorted(['member', 'editor', 'manager'])

    r = c.get('/api/v1/user/user1/+roles')

    assert sorted(r.json['group1']) == sorted(['member', 'editor', 'manager'])

    r = c.post_json('/api/v1/group/group1/+revoke',
                    {'mapping': {
                        'user1': ['manager']
                    }})

    assert r.json == {'status': 'success'}

    r = c.get('/api/v1/group/group1/+members')

    assert r.json['users'][0]['roles'] == ['member', 'editor']

    r = c.post_json('/api/v1/group/group1/+revoke', {
        'mapping': {'user1': ['editor', 'member']}
    })

    assert r.json == {'status': 'success'}

    r = c.get('/api/v1/group/group1/+members')

    assert len(r.json['users']) == 0

    r = c.delete('/api/v1/user/user1')

    assert r.json == {'status': 'success'}

    r = c.get('/api/v1/user/user1', expect_errors=True)

    assert r.status_code == 404
