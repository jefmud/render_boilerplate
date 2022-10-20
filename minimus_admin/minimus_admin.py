##############################
#
# Minimus Admin - implements Admin class user interface
# for use with minimus.
#
# There is some refactoring if you wanted to use with Flask.
# must have either MontyDB (stand-alone) or PyMongo (to a MongoDB instance)
# if you expect it to do anything
#
# License - MIT License, no guarantees of suitability for your app
#
##################################
__version__ = "0.0.4"
__author__ = 'Jeff Muday'
__license__ = 'MIT'

from minimus import Minimus, render_template, jsonify, parse_formvars, redirect, url_for, Session, abort
from montydb import MontyClient, set_storage
import json
from pymongo import MongoClient
from bson import ObjectId

import os
from passlib.context import CryptContext
import functools
from functools import wraps

pwd_context = CryptContext(
        schemes=["pbkdf2_sha256"],
        default="pbkdf2_sha256",
        pbkdf2_sha256__default_rounds=30000
)

def encrypt_password(password):
    return pwd_context.encrypt(password)

def check_encrypted_password(password, hashed):
    return pwd_context.verify(password, hashed)

# local session placeholder
_admin_session = None

class Admin:
    """
    Allow for CRUD of data in database
    TODO
	7. write up security for this, no security is included.  Possibly combine with minimus_users module.
	8. document the hell out of this module, because I will forget it.
    """
    def __init__(self, app:Minimus, 
                 session=None,
                 url_prefix="/admin",
                 db_uri=None,
                 db_file='minimus.db',
                 admin_database='minimus_admin',
                 users_collection='minimus_users',
                 require_authentication=True,
                 ):
        """__init__() - initialize the administration area"""
        global _db, _admin_session, _app
        self.app = app
        _app = app
        self.users_collection = users_collection
        
        
        self.require_authentication = require_authentication
        if require_authentication:
            if session is None:
                raise ValueError("Admin() requires a 'session' to attach to if 'require_authentication' is default or True")
            self.session = session
            _admin_session = session

        ### set up the database ###
        if db_uri:
            app.client = MongoClient(db_uri)
        else:
            set_storage(db_file)
            app.db_file = db_file
            app.client = MontyClient(db_file)
            
        app.db = app.client[admin_database]
        _db = app.db
        
        # get path for templates
        dirname = os.path.dirname(__file__)
        app.template_dirs.append(os.path.join(dirname, 'templates'))
        
        ### Add the routes ###
        app.add_route(url_prefix + '/login', self.login, methods=['GET','POST'], route_name="admin_login")
        app.add_route(url_prefix + '/logout', self.logout, route_name='admin_logout')
        ####
        app.add_route(url_prefix, self.view_all, route_name='admin_view_all')
        app.add_route(url_prefix + '/view/<coll>', self.view_collection, route_name="admin_view_collection")
        app.add_route(url_prefix + '/edit/<coll>/<id>', self.edit_fields, methods=['GET', 'POST'], route_name="admin_edit_fields")
        app.add_route(url_prefix + '/edit_schema/<coll>/<id>', self.edit_schema, methods=['GET', 'POST'], route_name="admin_edit_schema")
        app.add_route(url_prefix + '/edit_raw/<coll>/<id>', self.edit_json, methods=['GET', 'POST'], route_name="admin_edit_json")
        app.add_route(url_prefix + '/delete/<coll>', self.delete_collection_prompt, methods=['GET','POST'], route_name="admin_delete_collection")
        app.add_route(url_prefix + '/delete/<coll>/<id>', self.delete_collection_item, methods=['GET', 'POST'], route_name="admin_delete_collection_item")
        app.add_route(url_prefix + '/add/<coll>', self.add_collection_item, methods=['GET', 'POST'], route_name="admin_add_collection_item")
        app.add_route(url_prefix + '/add', self.add_mod_collection, methods=['GET','POST'], route_name="admin_add_collection")
        app.add_route(url_prefix + '/modify/<coll>', self.add_mod_collection, methods=['GET', 'POST'], route_name="admin_mod_collection")
        
        
    def login(self, env, filename=None, next=None):
        """
        login() - simple login with bootstrap or a Jinja2 file of your choice
        :param filename: the filename of the template to use
        :param next: the next page to go to after login
        """
        if filename is None:
            html = self.render_login()
        
        if env.get('REQUEST_METHOD') == 'POST':
            fields = parse_formvars(env)
            username = fields.get('username')
            password = fields.get('password')
            user = self.get_user(username)
            if self.authenticate(username, password):
                user['_id'] = str(user['_id'])
                self.login_user(user)
                next = 'admin_view_all' if next is None else next
                return redirect(url_for(next))
            
        # if no filename the render internal
        if filename is None:
            return html
        
        # render external login
        return render_template(filename)
    
    def login_user(self, user):
        """
        login_user() - login the user
            sets the Session to the authenticated user
            :param user: the user to login
        """
        self.session.connect()
        self.session.data['is_authenticated'] = True
        self.session.data['user'] = user
        self.session.save()
        
    def login_check(self):
        """
        login_check() - if require_authentication return user else None
        """
        if self.require_authentication:
            self.session.connect()
            if self.session.data.get('is_authenticated'):
                return self.session.data['user']
            return None
        else:
            return True

    def login_required(self, f):
        """login_required(f) is a decorator for Flask routes that require a login
        : param {f} : function to decorate
        : return : decorated function
        """
        @wraps(f)
        def decorated_function(*args, **kwargs):
            self.session.connect()
            if 'user' not in self.session.data:
                return redirect(self.app.url_for('admin_login'))
            return f(*args, **kwargs)
        return decorated_function

    def logout(self, env, next=None):
        """
        login_check(env, next) - if require_authentication return user else None
        """
        self.logout_user()
        next = next if next else '/'
        return redirect(next)
    
    def logout_user(self):
        """logout_user() - pops the user out of the session"""
        self.session.connect()
        if 'is_authenticated' in self.session.data:
            self.session.data['is_authenticated'] = False
        if 'user' in self.session.data:   
            self.session.data.pop('user')
        self.session.save()
    

    def view_all(self, env):
        """
        view_all(env) - view all collections in the database
        """
        if not self.login_check():
            return redirect(url_for('admin_login'))
        collections = self.app.db.list_collection_names()
        return render_template('admin/view_all.html', collections=collections)
    
    def view_collection(self, env, coll):
        """view_all(env, coll) - view a specific collection in the database"""
        if not self.login_check():
            return redirect(url_for('admin_login'))        
        data = list(self.app.db[coll].find())
        schema = self.app.db['_meta'].find_one({'name':coll})
        # santize id to string
        for doc in data:
            doc['_id'] = str(doc['_id'])
            
        if schema:
            # check for list-view
            if '^' in schema['schema']:
                docs = []
                for raw_doc in data:
                    this_doc = _schema_transform(raw_doc, schema)
                    docs.append(this_doc)
                return render_template('admin/view_collection_list.html', docs=docs, coll=coll)

        return render_template('admin/view_collection.html', coll=coll, data=data, schema=schema)


    def edit_json(self, env, coll, id):
        """render a specific record as JSON"""
        if not self.login_check():
            return abort(401)        
        try:
            key = {'_id': ObjectId(id)}
            data = self.app.db[coll].find_one(key)
        except Exception as e:
            return jsonify({'status': 'error', 'message': 'Admin edit_json(), ' + str(e)})
        
        if env.get('REQUEST_METHOD') == 'POST':
            try:
                raw = parse_formvars(env)
                text_format = raw.get('content')
                data = json.loads(text_format)
                #self.app.db[coll].update_one(key, {'$set': data})
                self.app.db[coll].replace_one(key, data)
            except Exception as e:
                return jsonify({'status': 'error', 'message': 'Admin edit_json, ' + str(e)})
            finally:
                return redirect(url_for('admin_view_collection', coll=coll))

        else:
            # render the JSON
            if '_id' in data:
                data.pop('_id')
            return render_template('admin/edit_json.html', coll=coll, content=json.dumps(data), error=None)


    def edit_fields(self, env, coll, id):
        """edit_fields(env, coll, id) - render a specific record as fields
		** combine with edit_schema() during refactor
		"""
        if not self.login_check():
            return abort(401)        
        try:
            if not id == 'new':
                key = {'_id': ObjectId(id)}
                old_data = self.app.db[coll].find_one(key)
            else:
                old_data = {}
        except Exception as e:
            return jsonify({'status': 'error', 'message': 'Admin edit_fields(), ' + str(e)})
        
        if env.get('REQUEST_METHOD') == 'POST':
            # write the data
            try:
                fields = parse_formvars(env)
                data = expand_fields(fields)

                # check which fields changed, add a blank field if it was removed
                for k,v in old_data.items():
                    if k not in data.keys():
                        data[k] = ''

                # clean up the data
                if '_id' in data:
                    data.pop('_id')
                if 'csrf_token' in data:
                    data.pop('csrf_token')

                # write the data
                if id == 'new':
                    id = self.app.db[coll].insert_one(data).inserted_id
                else:
                    self.app.db[coll].update_one(key, {'$set': data})
                data['_id'] = id
                
            except Exception as e:
                return jsonify({'status': 'error', 'message': 'Admin edit_fields(), ' + str(e)})
            finally:
                return redirect(url_for('admin_view_collection', coll=coll))
        else:
            # view the data
            try:
                data = self.app.db[coll].find_one(key)
                data['_id'] = str(data['_id'])
                fields = _fields_transform(data)
                return render_template('admin/edit_fields.html', coll=coll, fields=fields, id=data['_id'])
            except Exception as e:
                return jsonify({'status': 'error', 'message': 'Admin edit_fields(), ' + str(e)})
    
        
    def edit_schema(self, env, coll, id):
        """edit collection item with based on a schema
        env - the environment
        coll - collection name
        id - the database id
        """
        if not self.login_check():
            return abort(401)

        # get the data
        if id == 'new':
            data = {'_id': 'new'}
        else:
            try:
                key = {'_id': ObjectId(id)}
            except Exception as e:
                return jsonify({'status': 'error', 'message': 'Admin edit_schema(), ' + str(e)})

        # view the data
        try:
            schema = self.app.db['_meta'].find_one({'name':coll})
            if not id == 'new':
                # get existing data
                data = self.app.db[coll].find_one(key)

            fields = _schema_transform(data, schema)
            data['_id'] = str(data['_id'])
        except Exception as e:
            return jsonify({'status': 'error', 'message': 'Admin edit_schema(), ' + str(e)})
        finally:
            return render_template('admin/edit_schema.html', coll=coll, fields=fields, id=data['_id'])
        
    def add_collection_item(self, env, coll):
        """Add a new item to the collection, raw JSON"""
        if not self.login_check():
            return abort(401)        
        if env.get('REQUEST_METHOD') == 'GET':    
            return render_template('admin/add_json.html', coll=coll)
        else:
            fields = parse_formvars(env)
            raw = fields.get('content')
            try:
                data = json.loads(raw)
            except:
                data = cook_data(raw)
            self.app.db[coll].insert_one(data)
            data['_id'] = str(data['_id'])
        return redirect(url_for('admin_view_collection', coll=coll))
    
    def add_mod_collection(self, env, coll=None):
        """Add or Modify a collection"""
        if not self.login_check():
            return abort(401)        
        fields = {}
        key = None
        if coll:
            # find record of schema
            fields['name'] = coll
            rec = self.app.db['_meta'].find_one({'name':coll})
            if rec:
                key = {'_id': rec['_id']}
                fields['schema'] = rec['schema']
            
        if env.get('REQUEST_METHOD') == 'POST':
            fields = parse_formvars(env)
            name = fields.get('name')
            if name is None:
                return redirect( url_for('admin_view_all') )
            
            schema = fields.get('schema')
            meta = {'name': name, 'schema': schema}
            if schema:
                if key:
                    # since it exists, replace
                    self.app.db['_meta'].replace_one(key, meta)
                else:
                    # it's new insert
                    self.app.db['_meta'].insert_one(meta)
                
            # create the collection if it doesn't exist
            if not name in self.app.db.list_collection_names():
               id = self.app.db[name].insert_one({}).inserted_id
               self.app.db[name].delete_one({'_id':id})
            
            return redirect(url_for('admin_view_all'))
        
        return render_template('admin/add_mod_collection.html', fields=fields)
    
    def delete_collection_item(self, env, coll, id):
        if not self.login_check():
            return abort(401)        
        try:
            key = {'_id': ObjectId(id)}
            old_data = self.app.db[coll].find_one(key)
        except Exception as e:
            return jsonify({'status': 'error', 'message': 'deleteJSON non-existent id, ' + str(e)})
    
        self.app.db[coll].delete_one(key)
        return redirect(url_for('admin_view_collection', coll=coll))
    
    def delete_collection_prompt(self, env, coll):
        """delete collection with prompt"""
        if not self.login_check():
            return abort(401)        
        fields = {}
        if env.get('REQUEST_METHOD') == 'POST':
            fields = parse_formvars(env)
            if fields.get('name') == coll and fields.get('agree') == 'on':
                self.app.db[coll].drop()
            return redirect(url_for('admin_view_all'))
                
        return render_template('admin/delete_collection_prompt.html', fields=fields, coll=coll)
    
    def delete_collection(self, env, coll):
        """DANGER -- this method will delete a collection immediately"""
        if not self.login_check():
            return abort(401)        
        self.app.db[coll].drop()
        return redirect(url_for('admin_view_all'))
    
    def unit_tests(self):
        """simple test of connectivity.  more tests should be included in separate module"""
        name = '__test_collection'
        _id = self.app.db[name].insert_one({}).inserted_id
        names = self.app.db.list_collection_names()
        assert(name in names)
        self.app.db[name].drop()
        print("*** All tests passed ***")
        
    def get_users(self):
        """get_users() - return a list of all users JSON records"""
        if _db is None:
            raise ValueError("Database not initialized!")
        return list(_db[self.users_collection].find())
    
    def get_user(self, username=None, uid=None):
        """get_user(username, uid) ==> find a user record by uid or username
        : param {username} : - a specific username (string)
        : param {uid} : - a specific user id (string) - note, this is actual '_id' in databse
        : return : a user record or None if not found
        """
        if _db is None:
            raise ValueError("Database not initialized!")
        # first try the username--
        user = None
        if username:
            user = _db[self.users_collection].find_one({'username': username})
        if uid:
            user = _db[self.users_collection].find_one({'_id':uid})
        return user
    
    def create_user(self, username, password, **kwargs):
        """
        create_user(username, password, **kwargs) ==> create a user --
        : param {username} and param {password} : REQUIRED
        : param **kwargs : python style (keyword arguments, optional)
        : return : Boolean True if user successfully created, False if exisiting username
        example
        create_user('joe','secret',display_name='Joe Smith',is_editor=True)
        """
        user = self.get_user(username=username)
        if user:
            # user exists, return failure
            return False
        # build a user record from scratch
        user = {'username':username, 'password': encrypt_password(password)}
        for key, value in kwargs.items():
            user[key] = value
    
        _db[self.users_collection].insert_one(user)
        return True
    
    def update_user(self, username, **kwargs):
        """
        update_user(username, **kwargs) - update a user record with keyword arguments
        : param {username} : an existing username in the database
        : param **kwargs : Python style keyword arguments.
        : return : True if existing username modified, False if no username exists.
        update a user with keyword arguments
        return True for success, False if fails
        if a keyword argument is EXPLICITLY set to None,
        the argument will be deleted from the record.
        NOTE THAT TinyMongo doesn't implement $unset
        """
        user = self.get_user(username)
        if user:
            idx = {'_id': user['_id']}
            for key, value in kwargs.items():
                if value is None and key in user:
                    # delete the key
                    _db[self.users_collection].update_one(idx, {'$unset': {key:""}} )
                else:
                   # user[key] = value
                    if key=='password':
                        value = encrypt_password(value)
                    _db[self.users_collection].update_one(idx, {'$set': {key:value}} )
            return True
        return False
    
    def delete_user(self, username=None, uid=None):
        """delete_user(username, uid) deletes a user record by username or uid
        : param {username} : string username on None
        : param {uid} : string database id or None
        : return : returns user record upon success, None if fails
        """
        user = None
        if username:
            user = self.get_user(username=username)
        if uid:
            user = self.get_user(uid=uid)
        if user:
            _db[self.users_collection].remove(user)
        return user
    
    def authenticate(self, username, password):
        """
        authenticate(username, password) ==> authenticate username, password against datastore
        : param {username} : string username
        : param {password} : string password in plain-text
        : return : Boolean True if match, False if no match
        """
        user = self.get_user(username)
        if user:
            if check_encrypted_password(password, user['password']):
                return True
        return False
    
    def render_login(self, login_filename=None):
        """render_login(login_filename=None) returns a login page as a string contained
        login_file if None, then if loads module level file login.html
        : param {login_filename} : string of filename of login page HTML document or None.
        If None, then the package level standard login.html is loaded.
        : return : string HTML of login page
        NOTE: this is an experimental feature
        """
        # use module level 'login.html''
        if login_filename is None:
            moduledir = os.path.dirname(__file__)
            login_filename = os.path.join(moduledir, 'login.html')
        if not isinstance(login_filename, str):
            raise TypeError("ERROR: minmus_users.login_page() - login_filename must be a string")
        with open(login_filename) as fp:
            data = fp.read()
        return data
       
    
    def user_services_cli(self, args):
        """command line interface for user services"""
    
        error = 0
        errors = []
    
        if '--createuser' in args:
            username = input('Username (required): ')
            realname = input('Real Name: ')
            email = input('Email: ')
            password = input('Password (required):')
            self.create_user(username, password, realname=realname, email=email)
            print("*Created user*")
            return True
    
        if '--deleteuser' in args:
            print("Delete user--")
            username = input('Username (required): ')
            if self.delete_user(username):
                print("*Deleted user*")
                return True
            else:
                errors.append("No such user.")
    
        if '--listusers' in args:
            users = self.get_users()
            for user in users:
                print(user)
            return True
    
        if '--updateuser' in args:
            username = input('Username (required): ')
            realname = input('Real Name: ')
            email = input('Email: ')
            password = input('Password (required):')
            if self.get_user(username=username):
                self.update_user(username, password=password, realname=realname, email=email)
                print("*Updated user*")
                return True
            else:
                errors.append("No username exists.")
    
        host = '127.0.0.1'
        if '--host' in args:
            idx = args.index('--host')
            try:
                host = args[idx+1]
            except:
                error = 1
                errors.append("Bad or missing host.")
    
        port = 5000    
        if '--port' in args:
            idx = args.index('--port')
            try:
                port = int(args[idx+1])
            except:
                error = 1
                errors.append("Bad or missing port argument.")
    
        server = "wsgiref"        
        if '--server' in args:
            idx = args.index('--server')
            try:
                server = args[idx+1]
            except:
                error = 1
                errors.append("No server argument supplied.")
    
        if '--runserver' in args:
            if not error:
                try:
                    self.app.run(host=host, port=port, server=server)
                except Exception as e:
                    errors.append("Server error: " + str(e))
    
        print(', '.join(errors))
        usage = """
    Run usage:
        python app.py --runserver [--port {5000}] [--host {127.0.0.1}] [--server {wsgiref}]
    
    
    Other operations:
        python app.py [--createuser | --deleteuser | --listuser | --updateuser ]
    
        createuser - creates a new user
        deleteuser - deletes an existing user
        listusers - list all users
        updateuser - update an existing user
    """            
        print(usage)
        return False    
    

def _merge_dicts(dict1, dict2):
    """ 
    _merge_dicts(dict1, dict2) - merge two dictionaries, return the union.
    Using yield increases efficiency.
    From
    """
    for k in set(dict1.keys()).union(dict2.keys()):
        if k in dict1 and k in dict2:
            if isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
                # unfortunately, a recursive call
                yield (k, dict(_merge_dicts(dict1[k], dict2[k])))
            else:
                # If one of the values is not a dict, you can't continue merging it.
                # Value from second dict overrides one in first and we move on.
                yield (k, dict2[k])
                # Alternatively, replace this with exception raiser to alert you of value conflicts
        elif k in dict1:
            yield (k, dict1[k])
        else:
            yield (k, dict2[k])
    
def expand_fields(fields):
    """
    expand_fields(fields) - expand flattened fields to nested fields
    : params data - a flattened record
    returns expanded fields
    """
    data = {}
    for name, value in fields.items():
        data = dict( _merge_dicts(data, _nest_value(name, value)) )
    return data

def _nest_value(name, value):
    """
    _nest_value(name, value) - put the fields from a 
    "flattened" dotted name into nested structure and return
    
    :param name - the flattened dotted name
    :param value - the actual value
    
    return nested_value
    
    How can I do this cleaner with a dict structure?
    """
    data = {}
    parts = name.strip().split('.')
    if len(parts) == 1:
        data.update({parts[0]:value})
    elif len(parts) == 2:
        data.update({parts[0]: {parts[1]:value}})
    elif len(parts) == 3:
        data.update( {parts[0]: { parts[1] : { parts[2] : value } } } )
    else:
        raise ValueError("Schmema depth exceeds maximum limit of 3")
    return data
    

def _get_nested_value(name, data):
    """
    _get_nested_value(name, data) - get the fields from a "flattened" dotted name
    :param name - the flattened dotted name
    :param data - data dictionary of document
    return value
    """
    parts = name.strip().split('.')
    value = data
    for part in parts:
        value = value.get(part, '')
        if not isinstance(value, dict):
            return value
    return None


def _schema_transform(data, schema):
    """_schema_transform(data, schema) - create fields from data document and schema. These
    fields are used to create a form for editing the document. The fields are ordered.

    :param data - the document data
    :param schema - the document schema
    
    return
        fields
    
    A schema for each field is defined on one line as shown below.
    
    dataName : controlToUse :Label of the collection : type : defaultValue
    
    implemented:
    A caret (^) is used to indicate that the field is shown in a list-view.
    
    not implemented in this version:
    A asterisk (*) is used to indicate a required field.
    A pipe (|) is used to indicate a list of values.
    
    
    for example:
    ^name : textbox : Name
    
    
    type (simple types only)
    
    """
    # grab the schema buffer
    schema_lines = schema.get('schema').split('\n')
    fields = []
    for line in schema_lines:
        if line:
            field = {}
            
            # if there is an '_id' field, then this is an existing document
            if '_id' in data:
                field.update({'_id': data['_id']})
                
            # break it on ':'
            parts = line.split(':')
            
            # name part
            
            # is it a list-view field?
            field['list-view'] = '^' in parts[0]
            parts[0] = parts[0].replace('^', '')
            
            # is it a required field?
            field['required'] = '*' in parts[0]
            parts[0] = parts[0].replace('*', '')
            
            field['name'] = parts[0].strip() # the name part
            
            field['control'] = parts[1].strip() # get the type
            
            if len(parts) > 2: 
                field['label'] = parts[2].strip() # the label
            else:
                field['label'] = field['name'].title()
                
            if len(parts) > 3:
                field['type'] = parts[3].strip()
            
            # value for field(data) is none, get it from schema
            if data == {}:
                if len(parts) > 4:
                    field['value'] = parts[4].strip()
                else:
                    # if value is missing, make it an empty string
                    field['value'] = ''
            else:
                # transform multiple depths
                value = _get_nested_value(field['name'], data)
                field['value'] = value
                
            fields.append(field)
    return fields


def _unflatten(dictionary, separator='.'):
    """
    _unflatten(dictionary, separator='.') - unflatten a dictionary
    :param dictionary - the dictionary to unflatten
    :param separator - the separator to use
    return unflattened dictionary
    """
    resultDict = dict()
    for key, value in dictionary.items():
        parts = key.split(separator)
        d = resultDict
        for part in parts[:-1]:
            if part not in d:
                d[part] = dict()
            d = d[part]
        d[parts[-1]] = value
    return resultDict

def _flatten_dict(d, parent_key = '', sep='.'):
    """
    _flatten_dict(d, parent_key = '', sep='.') - flatten a nested dictionary
    :param d - the dictionary to flatten
    :param parent_key - the parent key
    :param sep - the separator
    return flattened dictionary
    """
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def _fields_transform(fields):
    """transform fields to be used in form"""
    # flatten dictionary if needed
    f_fields = _flatten_dict(fields)
    nfields = []
    for key, value in f_fields.items():
        nf = {}
        nf['name'] = key
        nf['value'] = str(value)
        nf['label'] = key.capitalize()
        if '\n' in nf['value']:
            nf['type'] = 'textarea'
        else:
            nf['type'] = 'text'
        nfields.append(nf)
    return nfields

def cook_data(raw_data):
    """cook data to be used in form"""
    data = {}
    lines = raw_data.split('\n')
    for line in lines:
        if ':' in line:
            key, value = line.split(':')
            key = key.strip()
            data[key] = value.strip()
    return data

def login_required(f):
    """login_required(f) is a decorator for Flask routes that require a login
    : param {f} : function to decorate
    : return : decorated function
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        _admin_session.connect()
        if 'user' not in _admin_session.data:
            return redirect(_app.url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

if __name__ == '__main__':
    print(f"Minimus Admin - VERSION {version}")
    print("... Minimus Admin is not intended for direct execution. ...")
    app = Minimus(__name__)
    admin = Admin(app, require_authentication=False)
    admin.unit_tests()
    print("done")
