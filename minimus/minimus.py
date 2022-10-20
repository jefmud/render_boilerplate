###########################################
#
# Minimus - a minimal web framework inspired by
#   Bottle, Flask, Pyramid, and Paste
#
#   Early ALPHA version 2021
#    by Jeff et. al.
#    MIT License
#
#     Some code is influenced and borrowed
#     from Python Paste (under MIT license)
#       by Chris Dent (https://pypi.org/project/Paste/)
#
#       and
#
#    Jinja2 best of class Templating
#     from the Pallets project (https://palletsprojects.com/p/jinja/)
#
#    Other Python standard libraries included
#    also, waitress and gevent are excellent
#    choices for alternate WSGI servers
#
###########################################
_version_ = '0.0.9.2rc'
_author_ = 'Jeff Muday'
_license_ = 'MIT'

_logo_text=\
r"""
  __  __ _       _
 |  \/  (_)     (_)
 | \  / |_ _ __  _ _ __ ___  _   _ ___
 | |\/| | | '_ \| | '_ ` _ \| | | / __|
 | |  | | | | | | | | | | | | |_| \__ \
 |_|  |_|_|_| |_|_|_| |_| |_|\__,_|___/
------------------------------------------
 A Minimal Python Framework
 (C) {} Jeff et. al. 
 Version {}, (use grant MIT License)
 -----------------------------------------
"""

import base64
import cgi
import datetime
import http.client
from http.cookies import SimpleCookie, Morsel, CookieError
import json
import mimetypes
import os
import pathlib
import pickle
import random
import string
import sys
import time
from urllib.parse import parse_qsl

# from pallets project, best of class template engine
from jinja2 import Environment, FileSystemLoader

class JSObj(dict):
    """a utility class that mimics a JavaScript Object"""
    def __getattr__(self, attr_name):
        if attr_name in self:
            return self[attr_name]
        else:
            return None
    def __setattr__(self, attr_name, attr_value):
        self[attr_name] = attr_value
    def __delattr__(self, attr_name):
        if attr_name in self:
            del self[attr_name]
        else:
            raise AttributeError(f"JSObj().__delattr__({attr_name}) - No such attribute")
        
# available (module only) private, yet global!
_app = None
_app_dir = None
_static_dir = None
_template_dirs = None
_cookie_list = None

# works with flash, you can change it if you want
_flashdelimiter = '___'
_flash_cookie_prefix = '_flash_'

# The global object, available to all routes, templates, etc.
# dangerous, don't use except for UNIVERSAL settings
g = JSObj()


def token_generator(size=12, chars=string.ascii_uppercase + string.digits):
    """token_generator(size, chars) - generate a random token base on string lib"""
    return ''.join(random.choice(chars) for _ in range(size))
    

def cookie_header(name, value, secret=None, days=30, charset='utf-8', path='/'):
    """cookie_header() - create a cookie-header tuple"""
    if not isinstance(value, str):
        raise ValueError('add_cookie value must be a string type')
    dt = datetime.datetime.now() + datetime.timedelta(days=days)
    fdt = dt.strftime('%a, %d %b %Y %H:%M:%S GMT')
    secs = days * 86400
    if secret:
        if isinstance(secret, str):
            b = secret.encode(charset)  # bytes
        else:
            b = secret
        value = encrypt(b, value).decode(charset, 'ignore')
    header_str = ('Set-Cookie', '{}={}; Expires={}; Max-Age={}; Path={}'.format(name, value, fdt, secs, path))
    return header_str       
        
# Request object class
class Request(JSObj):
    """
    Bottle, Pyramid, and Flask-like adapter, a very imcomplete clone of the Flask request object
    as it is better than the others.
    
    I will add more as I need them.
    
    Really, this is not needed since you can get it all from the ENVIRONMENT
    """
    def __init__(self, env):

        self.method = env['REQUEST_METHOD']
        self.form = parse_formvars(env)
        self.cookies = get_cookies(env)
        self.args = parse_querystring(env)
        self.path = env['PATH_INFO']
        self.is_json = self.path.endswith('.json')
        
# important Response object
class Response:
    """Response() - important WSGI requires Response object.  All requests get
       responses!
       
       This class wraps the response body and headers
    """
    def __init__(self, response_body=None, status_code=200, headers=None, charset='UTF-8'):
        global _cookie_list
        self.charset = charset
        self._headers = []
        # if another Response object is sent
        if isinstance(response_body, Response):
            # Make a response from a Response.
            status_code = response_body.status_code
            headers = response_body.headers
            response_body = response_body.body
            
        if isinstance(response_body, ClassView):
            """Make a response from a class-based view"""
            status_code = response_body.response.status_code
            headers = response_body.response.headers
            response_body = response_body.response.body
        
        # if a tuple is used to instantiate
        if isinstance(response_body, tuple):
            if len(response_body) == 3:
                headers = response_body[2]
                status_code = response_body[1]
                response_body = response_body[0]
            if len(response_body) == 2:
                status_code = response_body[1]
                response_body = response_body[0]
                headers = response_body.headers
        
        if isinstance(status_code, str):
            # if status code came as a string, convert to int
            status_code = int(status_code.split(' ')[0])

        self.status_code = status_code

        if response_body is None:
            # make an empty response which is a status_str
            response_body = self.status

        self.response_body = response_body
        self.add_header(headers)
        if _cookie_list:
            # set cookies if requested
            self.add_header(_cookie_list)
            _cookie_list = None

    @classmethod
    def create_from_handler(cls, handler_response):
        """A class factory from handler/callback response"""
        if isinstance(handler_response, Response):
            if _cookie_list:
                handler_response.add_header(_cookie_list)
            return cls(handler_response.body, handler_response.status, handler_response.headers)
        if isinstance(handler_response, tuple):
            if len(handler_response) == 3:
                if _cookie_list:
                    handler_response[2].add_header(_cookie_list)
                return cls(handler_response[0], handler_response[1], handler_response[2])
            if len(handler_response) == 2:
                return cls(handler_response[0], handler_response[1], headers=_cookie_list)
        elif isinstance(handler_response, str) or isinstance(handler_response, dict):
            return cls(handler_response, headers=_cookie_list)
        else:
            pass
        return cls('Incompatible response', 400)

    def add_cookie(self, name, value, secret=None, days=365, path='/'):
        header_str = cookie_header(name=name, value=value, secret=secret, days=days, path=path)
        self.add_header(header_str)

    def set_cookie(self, name, value, secret=None, days=365):
        # to be compatible with flask
        self.add_cookie(name, value, secret, days)
        
    def delete_cookie(self, name):
        self.add_cookie(name, '', days=0)

    def add_header(self, headers):
        for header in self._headers:
            if header == headers:
                return

        if isinstance(headers, str):
            # if headers was given as a string
            self._headers.append(('Content-Type', headers))
        elif isinstance(headers, tuple):
            # headers given as a tuple
            self._headers.append(headers)
        elif isinstance(headers, list):
            # user gave us a fully formed header
            self._headers += headers
        else:
            pass

    def add_headers(self, headers):
        self.add_header(headers)

    @property
    def content_length_header(self):
        try:
            body = self.body[0]
            return [('Content-Length', str(len(body)))]
        except:
            return [('Content-Length', '0')]

    def handle_as_json(self):
        response_body = json.dumps(self.response_body).encode(self.charset, 'ignore')
        self.add_header( ('Content-Type',f'application/json;charset={self.charset}') )
        return[response_body]

    def response_encode(self):
        """encode our response to be a list of encoded strings"""
        if isinstance(self.response_body, str):
            return [self.response_body.encode(self.charset, 'ignore')]
        elif isinstance(self.response_body, list):
            if len(self.response_body) > 0 and isinstance(self.response_body[0], dict):
                return self.handle_as_json()
            return self.response_body
        elif isinstance(self.response_body, dict):
            # encode and return JSON, may have to get BSON for some encodings
            return self.handle_as_json()
        else:
            # it's already binary
            pass
        return [self.response_body]


    def __repr__(self):
        # build the status string, using the standard helper
        if not self._headers:
            self._headers = [('Content-Type', f'text/html;charset={self.charset}')]

        return f'Response({self.body}, {self.status}, {self.headers}'

    def __call__(self):
        return self.body, self.status, self.headers

    @property
    def body(self):
        return self.response_encode()

    @property
    def status(self):
        rstr = http.client.responses.get(self.status_code, 'UNKNOWN')
        return f"{self.status_code} {rstr}"

    @property
    def headers(self):
        if not self._headers:
            self._headers = [('Content-Type', f'text/html;charset={self.charset}')]
        return self._headers + self.content_length_header

    @property
    def wsgi(self):
        return self.body, self.status, self.headers
    
class ClassView:
    """Minimus class view base type
    
    example -- using route decorator
    
    @app.route('/myview)
    class MyView(ClassView):
        def get(self, env):
           return "Hello World!"
    """
    def __init__(self, env, **kwargs):
        self.env = env
        # possibly remove the environment since it is local to the ClassView
        self.response = self.dispatcher(env, **kwargs)
    
    def dispatcher(self, env, **kwargs):
        """dispatcher for the class view GET, POST, PUT, DELETE, etc"""
        request_method = env.get('REQUEST_METHOD')
        if request_method == 'GET':
            return Response( self.get(env, **kwargs) )
        if request_method == 'POST':
            return Response( self.post(env, **kwargs) )
        if request_method == 'PUT':
            return Response( self.put(env, **kwargs) )
        if request_method == 'DELETE':
            return Response( self.delete(env, **kwargs) )
            
    def __len__(self):
        return len(self.response.body)
    
    def get(self, env):
        return Response("GET ClassView method not defined", 405)
    def post(self):
        return Response("POST ClassView method not defined", 405)
    def put(self):
        return Response("PUT ClassView method not defined", 405)
    def delete(self):
        return Response("DELETE ClassView method not defined", 405)
    
    def __repr__(self):
        return self.response 
    
class FieldData:
    """helper class for FormData"""
    def __init__(self, value):
        self.data = value
    def __repr__(self):
        return self.data
        
class FormData:
    """helper class for form data"""
    def __init__(self, env):
        fields = parse_formvars(env)
        for k,v in fields.items():
            self.__setattr__(k,FieldData(v))    
            
class Session:
    """session object class
    __init__(params) - creates a session object
    
    params:
        app - the flask app object
        sessions_dir - the directory to store the sessions in (defaults to './sessions')
        cookie_name - the name of the cookie to identify the session (defaults to 'msession')
        mode - the mode of the session storage, 'memory' or 'file' (defaults to 'memory')
        days - the number of days to keep the session in memory (defaults to 30)
    

    Example usage -- using session
    at the top of your app.py file include the line
    session = Session(app)
    
    in each view function, include the code or put it in @app.before_request()
    def some_func():
        session.connect()
        session.data['user'] = 'joe'
        session.data['age'] = '30'
        # note that when 'file' mode is used
        # it is not saved until session.save() is called
        # and is optional (inert) if you are using 'memory' mode
        session.save()
    
    """
    def __init__(self, app, sessions_dir='./sessions', cookie_name='msession', mode='memory', days=30):
        self._app = app
        self._cookie_name = cookie_name
        self._dir = sessions_dir
        self._key = None
        self.data = {} # to ensure compatibility with original version
        if mode not in ['file', 'memory']:
            raise ValueError("ERROR: Session mode must be 'file' or 'memory'")
        self._mode = mode # file, memory, or memcached (FUTURE)
        self._sessions = {}
    
    @property
    def session_key(self):
        """property returns a session key
        if none, then use the randomly generated one
        """
        this_session_key = get_cookie(_app.environ, self._cookie_name)
        if this_session_key:
            # if there is a session key, use it
            self._key = this_session_key
        else:
            # generate a new key token
            self.new()
        return self._key
    
    def commit(self):
        """save the session to disk/cache, could be called after every request.
        you would also probably NOT want to call this in 'after_request', for efficiency
        """
        self._save(self.session_key)
        
    def save(self):
        """save the session to a file"""
        self.commit()
        
    def new(self):
        """
        new() - creates a new session cookie,
            purge old session (if any), blanks out the data
        """
        #self.purge()
        self._key = token_generator(32)
        self.data = {}
        set_cookie(self._cookie_name, self._key)
        return self._key
        
    def connect(self):
        """
        connect() - connects to a session if one exists, otherwise creates a new one.
        You can call this at the top of your view function or in @app.before_request().
        """
        self._load(self.session_key)
        
    def _session_fname(self, session_key):
        """_session_fname() - private function to make a directory for Sessions.
        If 'file' mode and it doesn't exist and return filename,
        else if 'memory' mode, return None
        """
        if self._mode == 'file':
            os.makedirs(self._dir, exist_ok=True)
            return os.path.join(self._dir, str(session_key))
        return None
    
    def _load(self, session_key=None):
        """_load() - private function to load the session from disk/cache"""
        fname = self._session_fname(self.session_key)
        if session_key is None:
            # if no session key, then load the current session
            session_key = self.session_key
        if self._mode == 'file':
            if os.path.exists(fname):
                with open(fname, 'rb') as fin:
                    self.data = pickle.load(fin)
            else:
                self.data = {}
                self._save(session_key)
        elif self._mode == 'memory':
            if session_key in self._sessions:
                self.data = self._sessions[session_key]
            else:
                self._sessions[session_key] = {}
        else:
            raise Exception(f"unknown Session mode: {self._mode}")
        #print(f"Session[{session_key}] loaded: {self.data}")
                
    def _save(self, session_key=None):
        """_save() - private function to save the session to disk/cache
                returns the None
        """ 
        if session_key is None:
            session_key = self.session_key 
        if self._mode == 'file':
            fname = self._session_fname(self.session_key)
            try:
                with open(fname, 'wb') as fout:
                    pickle.dump(self.data, fout)
            except Exception as e:
                print('ERROR: Session save failed:', e)
        
    def purge(self):
        """purge() - purge old session if needed"""
        if self._mode == 'file':
            if os.path.exists(self._session_fname(self.session_key)):
                os.remove(self._session_fname(self.session_key))
        elif self._mode == 'memory':
            if self._key in self._sessions:
                del self._sessions[self._key]
        self.data = {}
        
    def clear(self):
        """clear() - clears the session. Same as purge()"""
        self.purge()
    

def redirect(url, code=None):
    """redirect(url, code=status)
            function leverages app object method to redirect
            see Mimimus.redirect() for more info
    """
    return _app.redirect(url, code=code)
    
def url_for(route_name, **kwargs):
    """url_for(route_name, **kwargs) - leverages app object method
        to generate a url with the route_name and kwargs
    """
    return _app.url_for(route_name, **kwargs)


def abort(*args, **kwargs):
    """abort(code, message=None, **kwargs) - leverages app object method
            to build a response with the code and message
    """
    return _app.abort(*args, **kwargs)


def jsonify(data):
    """jsonify(obj) - exposes internal app object method
            to build a response with the obj
    """
    return _app.jsonify(data)
    
# local utilities
def mimeguess(filename):
    """mimeguess() - guess mimetype from filename, path, or url.
    does not work for all mimetypes, but works for most.

    Args:
        filename (str): a filename str to check

    Returns:
        str: returns a mimetype guess for the file

    Example:
       mimeguess('MyPicture.png') ==> 'image/png'
    """
    ext = '.' + filename.split('.')[-1].lower()
    return mimetypes.types_map.get(ext,'text/html')

def search_file(filename, *args):
    """search_file(filename, *args) - look for a filename in several locations,
    return the actual filename that is found first or None

    Args:
        filename (str): the file to search for existence
        *args (str): 0 or more directories to examine

    Returns:
        str: the full path of the exisiting file or None
    """
    fname = filename
    if filename.startswith('/'):
        fname = filename[1:]
    # possible paths ACTUAL PATH, relative path to app, or template_dirs
    # might want to make this more specific to avoid name conflict

    paths = [filename, fname]
    for arg in args:
        if isinstance(arg, list):
            for sub in arg:
                paths.append(os.path.join(sub, fname))
        else:
            paths.append(os.path.join(arg, fname))

    for fn in paths:
        #if os.path.exists(fn):
        # *** better way ***
        path = pathlib.Path(fn)
        if path.is_file():        
            return fn
    return None

def flash(*args, **kwargs):
    """hook to Minimus flash messages"""
    return _app.flash(*args, **kwargs)
    
def get_flashed_messages():
    """ hook to Minimus object """
    return _app.get_flashed_messages()

def route_match(route, path):
    """check if a Mimimus route and env PATH_INFO match and
    parse the keyword arguments in the path.

    Args:
        route (str): Mimimus route. Expects framework route syntax
        path (str): actual url PATH_INFO request
    Returns:
        bool, dict: True/False on route matching path, dict contains matching keyword args

    Explanation:
       route is of the form "/thispage"
       or a route with a variable "/thispage/<varname>"
       or the SPECIAL path "/something/<path:mypath>" which captures
          an entire path in that position.  <path:mypath> is a GREEDY capture
          and will capture the entire path following.

    Example:
        route_match('/hello','/hello') ==> True, {}
        route_match('/hello/<name>', '/hello/World') ==> True, {"name":"World"}
        route_match('/<blogname>/<entryname>', '/Wonderblog/I-am-the-Walrus')
            ==> True, {"blogname":"WonderBlog", "entryname":"I-am-the-Walrus"}
            
        # NOTE this works
        route_match('/<path:mypath>', '/Wonderblog/I-am-the-Walrus/')
            ==> True, {"mypath":"Wonderblog/I-am-the-Walrus/"}
            
        # NOTE this will not work because the path is GREEDY and will capture
        # all the path.  I will fix this in the future
        route_match('/<path:mypath>/edit', '/Wonderblog/I-am-the-Walrus/edit')
            ==> True, {"mypath":"Wonderblog/I-am-the-Walrus/edit"}
    """
    # explode the route and path parts
    rparts = route.split('/')
    pparts = path.split('/')
    # return keyword arguments as kwargs
    kwargs = {}
    if not('path:' in route) and (len(rparts) != len(pparts)):
        return False, kwargs
    for idx, rp in enumerate(rparts):
        # handle variable in the path
        if '<' in rp:
            # handle variable
            b1 = rp.find('<')
            b2 = rp.find('>')
            if b2 <= b1:
                # malformed, fail
                return False, kwargs
            varname = rp[b1+1:b2]
            if 'path:' in varname:
                varname = varname.replace('path:','')
                i = idx
                pathval = ""
                while i < len(pparts):
                    pathval += '/' + pparts[i]
                    i += 1
                #todo, escape the pathval
                if pathval.startswith('/'):
                    pathval = pathval[1:]
                kwargs[varname] = pathval
                return True, kwargs
            else:
                kwargs[varname] = pparts[idx]
        elif rp != pparts[idx]:
            return False, kwargs
    # all done, the path matched and here are the keyword args (if any)
    return True, kwargs

def route_encode(route, **kwargs):
    """given a route and matching kwargs, return a URL

    Args:
        route (str): a route string in route syntax
        **kwargs (keyword arguments): keywords should match varnames in route

    Returns:
        str: returns the path from route and keyword args

    Example:
        route = '/hello/<name>' kwargs={"name":"George"}
        route_encode('/hello/<name>', name="George") ==>
            /hello/George
    """
    # explode the route and path parts
    try:
        rparts = route.split('/')
    except Exception as ex:
        print(ex)
        return "_ERROR_in_route_encode_"
    
    nparts = []
    for rp in rparts:
        if '<' in rp:
            # handle variable
            b1 = rp.find('<')
            b2 = rp.find('>')
            if b2 <= b1:
                # malformed, fail
                return False, kwargs
            varname = rp[b1+1:b2]
            varval = kwargs.get(varname, None)
            if varval:
                nparts.append(str(varval))
            else:
                raise ValueError(f"route_encode({route}, {kwargs}) - {varname} not in keyword args")
        else:
            nparts.append(rp)
    url = '/'.join(nparts)
    return url


def get_file(filename, *args, **kwargs):
    """get_file(filename, *args, **kwargs) - get text file or return None,
    searches the likely paths to find the file. If not found, return None

    Args:
        filename (str): a filename to search
        *args (str): multiple directory candidates for file location first one to match wins
        **kwargs (keyword arguments): default ftype='text' also would use ftype='binary'

    Example:
        get_file('index.html', 'templates', ftype='text')
        get_file('mylogo.gif', 'static/images', ftype='binary')
    """
    real_filename = search_file(filename, *args)
    file_contents = None
    path = pathlib.Path(real_filename)
    if path.is_file():
        if real_filename:
            if 'bin' in kwargs.get('ftype',''):
                # binary file types
                with open(real_filename, 'rb') as fp:
                    file_contents = fp.read()
            else:
                with open(real_filename) as fp:
                    file_contents = fp.read()

    return file_contents

def get_text_file(filename, *args):
    """call get_file for a text file - looks for the file in multiple directorys

    Args:
        filename (str) - a filename
        *args (str) - 0 or more directories to return a file from

    Returns:
        str: the contents of the file or None

    see "get_file"
    """
    return get_file(filename, *args)

def get_file_size(filename, *args):
    """return the size of a filename, search likely paths

    Args:
        filename (str) - a full pathname or relative path name of a file
        *args (str) - 0 or more paths under which to locate the file

    Returns:
        int: the size in bytes of the file
    """
    real_filename = search_file(filename, *args)
    if real_filename:
        return os.path.getsize(real_filename)
    return 0

def ext_check(pathname, ext_list):
    """check if pathname has an extension in the ext_list

    Args:
        pathname (str): some pathname with file and extension
        ext_list (list of str): a list of extensions

    Returns:
        bool: True if pathname ends in one of the extensions

    Usage:
        x = 'MyPicture.png'
        if ext_check(x, ['jpg','png','jpeg']):
            print(x, "is a picture")

    """
    for ext in ext_list:
        if pathname.lower().endswith(ext.lower()):
            return True
    return False

def real_path(path):
    """real_path(path) - returns the full path in the OS
    Args:
        path (str) - the path or relative path
    Returns:
        (str) - the full path in the OS
    """
    return os.path.dirname(os.path.realpath(path))

def header_get(headers, header_key):
    """header_get() - return a header value given a particular header_key
    Args:
        headers (list): a list of headers in WSGI Response
        header_key (str): a string key to be searched in a header
    Returns:
        str: The header value or None if not found
    """
    for header in headers:
        if header[0].lower() == header_key.lower():
            return header[1]
    return None


def _get_cookies(environ):
        """
        _get_cookies(environ) - Gets a cookie object (which is a dictionary-like object) from the
        request environment; caches this value in case _get_cookies is
        called again for the same request.
        """
        header = environ.get('HTTP_COOKIE', '')
        if 'minimus.cookies' in environ:
            cookies, check_header = environ['minimus.cookies']
            if check_header == header:
                return cookies
        cookies = SimpleCookie()
        try:
            cookies.load(header)
        except CookieError:
            pass
        environ['minimus.cookies'] = (cookies, header)
        return cookies

def get_cookies(environ, secret=None):
    """get_cookies() - return a cookie object from the request environment
    Args:
        environ (dict): the WSGI environment

    Returns:
        list: a list of dictionaries with cookie name and value
    """
    cookies_raw = _get_cookies(environ)
    cookies = []
    for key, value in cookies_raw.items():
        cookie = { key: get_cookie(environ, key, secret)}
        cookies.append(cookie)
        
    return cookies

def get_cookie(environ, name, secret=None, charset='utf-8'):
    """get a named cookie from the environment

    Args:
        environ (dict): the WSGI environment which should contain any cookies
        name (str): the name of the cookie to retrieve
        secret (str): a server-side secret for signed cookies
        charset (str): the character set for the cookie value
    Returns:
        str: the cookie value or None
    """
    cookies = _get_cookies(environ)
    morsel = cookies.get(name)
    value = None
    if morsel:
        if secret:
            value = decrypt(secret, morsel.value)
            if not isinstance(value, str):
                value = value.decode(charset)
        else:
            value = morsel.value
    return value

def set_cookie(name, value, path='/', days=30, secret=None, charset='utf-8'):
    """set_cookie(name, value) - append a cookie in the _cookie_list
    the WSGI Response will set the _cookie_list in the response headers.

    Args:
        name (str): the name of the cookie to set
        value (str): the value of the cookie
        path (str): the path of the cookie, defaults to '/'
        days (float): the max age of the cookie in days. default is 30
        secret (str): a server-side secret for signed cookies, default None
        charset (str): the character set for the cookie value, default 'utf-8'
    """
    global _cookie_list
    if ' ' in value:
        value = f'"{value}"'
    cookie = cookie_header(name=name, value=value, secret=secret, days=days, path=path, charset=charset)
    if _cookie_list:
        _cookie_list.append(cookie)
    else:
        _cookie_list = [cookie]
        
def delete_cookie(name):
    """
    delete_cookie(name) - there is no actual delete cookie, but you can
    set it to blank with a duration of 0 days.
    """
    set_cookie(name, '', days=0)
   
def _prune_headers(headers):
    """_prune_headers() - remove headers that are duplicate
    internal function, who would want to use it?
    """
    pruned_headers = []
    headlen = len(headers)
    header_count = {}
    for i in range(headlen):
        header = headers[headlen-i-1]
        header_type = header[0].lower()
        if header_type in ['content-type', 'content-length', 'content-encoding', 'content-language', 'content-location', 'content-md5', 'content-range', 'content-type', 'expires', 'last-modified', 'set-cookie', 'cache-control', 'pragma']:
            header_count[header_type] = header_count.get(header_type, 0) + 1
            if header_count[header_type] <= 1:
                pruned_headers.append(header)
        else:
            pruned_headers.append(header)
        
    return pruned_headers

# #############################
# our Framework Minimus, no magic here, just a big engine!
#
class Minimus:
    def __init__(self, app_file, template_dirs=None,
                 static_dir="static", quiet=False, graphic_types=None, charset='UTF-8'):
        """Minimus initialization

        Args:
            app_file (str): required, typically '__main__' used to establish real OS path
            template_dirs (list): paths or relative paths to template directory default=["templates"]
            static_dir (str): path or relative path to static files default="static"
            quiet (bool): used in development mode to see environmen on the console default=False
            graphic_types (list of string): used for overide file types of ['jpg', 'jpeg', 'gif', 'png', 'ico', 'svg']
            charset (str): used for response encoding default='UTF-8'

        Example:
            from minimus import Minimus
            app = Minimus(__name__)
        """
        global _app, _app_dir, _template_dirs, _static_dir, session # module will need this
        self.routes = None
        
        if template_dirs is None:
            template_dirs = ["templates"]
            
        # minimus config
        self.config = JSObj()
        
        if graphic_types is None:
            # known graphic types
            self._graphic_types = ['jpg', 'jpeg', 'gif', 'png', 'ico', 'svg']
        else:
            # just in case user requires overide
            self._graphic_types = graphic_types

        # make sure we know the current app's directory in self and module
        self.secret_key = None
        self.cookies = {}
        self.debug = False
        self.charset = charset
        self.quiet = quiet
        self.app_dir = os.path.dirname(os.path.realpath(app_file))
        _app = self
        _app_dir = self.app_dir
        self.static_dir = static_dir
        _static_dir = static_dir
        self.template_dirs = template_dirs
        _template_dirs = self.template_dirs        
        
        # request "hook" can be replaced by external callback
        # a little ugly to do this way, but works
        self.not_found_html = self._not_found_html
        self.app_before_request = self._before_request
        self.app_after_request = self._after_request
        # receives template filters
        self.template_filters = {}

        # place holders
        self.environ = None
        self.start_response = None
        self.request = None


    def response_encode(self, x):
        if isinstance(x, str):
            return [x.encode(self.charset, 'ignore')]
        else:
            return [x]
        return x

    def _before_request(self, environ):
        """this is a hookable callback for BEFORE REQUEST"""
        pass

    def _after_request(self, environ):
        """this is a hookable callback for AFTER REQUEST"""
        pass

    def app_middlewares(self, environ, start_response):
        """ This is were the middleware overrides will happen"""
        return environ, start_response
    
    def abort(self, status_code:int, html_msg=None):
        """an abort response, well... could be anything"""
        rstr = http.client.responses.get(status_code, 'UNKNOWN')
        if html_msg is None:
            html_msg = f'<h1>{status_code} {rstr}</h1>'
        return Response(response_body=html_msg, status_code=status_code)

    def wsgi(self, environ, start_response):
        """The main WSGI application.  Supports WSGI standard can be exposed to
        work with external WSGI servers.

        In the __main__ you could do this below.  Then Gunicorn can hook onto
        it  $ gunicorn app.wsgi -b 127.0.0.1:8000

        # app.py
        app = Minimus(__name__)
        wsgi = app.wsgi
        """
        # save these to the object -may be needed by downstream methods
        self.start_response = start_response
        self.environ = environ

        # debug shows environment on server console
        if self.debug:
            print("-"*50)
            print(environ)

        # before request -- can be "hooked" at application level
        pre_cookies = _get_cookies(environ)
        
        # before request
        self.app_before_request(environ)

        # app middlewares
        self.app_middlewares(environ, start_response)
        
        # route dispatcher
        path_info = environ.get('PATH_INFO')
        response_body, status_str, headers = self.render_to_response(path_info)
        
        # after request
        self.app_after_request(environ)
        
        # look for special session cookie injection
        post_cookies = _get_cookies(environ)
        if post_cookies != pre_cookies:
            # if msession is set
            session_key = get_cookie(environ, 'msession')
            if session_key:
                header = cookie_header('msession', session_key)
                headers.append(header)

        # make sure headers are not duplicated
        headers = _prune_headers(headers)

        # classic WSGI return
        start_response(status_str, headers)
        return iter(response_body)
     
        
    def add_route(self, route, handler, methods=None, route_name=None):
        """simple route addition to Mimimus application object
        :param route: - supports simple static routes (must begin with a slash) as well as named variables.
        It also supports a special PATH catchment variable e.g. "/blog/<mypath:path>"
        handler - callback function that handles the route.  By default the callback's first
        parameter is an environment variable.  The callback can also have OTHER paramerters that
        match the variables.
        :param methods: (list) - HTTP Methods supported, by default it supports ["GET"]
                   but can be ["POST", "GET", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"]
        :param route_name: - the name of the route used by app.url_for(name) routing
        """
        if methods is None:
            methods = ['GET']
        if not (isinstance(methods, list) or isinstance(methods, tuple)):
            raise ValueError('Minimus add_route route={} methods must be a list or tuple of string methods')
        if self.routes is None:
            self.routes = []
        # avoid duplication
        for r in self.routes:
            if r == route:
                return
        # finally, add route tuple
        self.routes.append((route,handler, methods, route_name))

    def _not_found_html(self):
        """just return some text for the 404.  This can be replaced with app level function
        # app.py
        app = Minimus(__name__)
        def my404():
            return "My 404 message!"
        app.not_found_html=my404
        """
        return '<h1>404</h1><p>Not Found</p>'

    def run(self, host='127.0.0.1', port=5000, server='wsgiref', debug=False, keyfile=None, certfile=None, quiet=False):
        """run() starts a "internal" server at host/port with server
        :param host: default=127.0.0.1, but can be '0.0.0.0' for serve to all
        :param port: default=5000
        :param server: default='wsgiref' other servers supported 'paste','waitress','gevent'
        """
        if not server in ['wsgiref','paste','waitress','gevent', 'twisted']:
            raise ValueError('Minimus run server={} not supported'.format(server))
        
        print(self.logo())

        self.debug = debug
        self.host = host
        self.port = port
        self.server = server

        if server == 'paste':
            """Start the server with the paste server.  Can be used for development and production
            Unfortunately, it does not support SSL and is not actively maintained.
            Very stable, decent performance.
            """
            from paste import httpserver
            from paste.translogger import TransLogger
            handler = TransLogger(self.wsgi, setup_console_handler=(not self.quiet))
            print("Starting Paste Server")
            httpserver.serve(handler, host=host, port=port)

        if server == 'wsgiref':
            """Basic wsgiref server.  Good for development only."""
            from wsgiref.simple_server import make_server
            with make_server(host, port, self.wsgi) as httpd:
                print("WSGIREF Serving on {}:{}".format(host, port))
                httpd.serve_forever()

        if server == 'gevent':
            """Gevent server, high speed, but no threading. Supports SSL (if keyfile and certfile are set)"""
            from gevent import pywsgi
            address = (host, port)
            print("Gevent serving on {}:{}".format(host, port))
            httpd = pywsgi.WSGIServer(address, self.wsgi, keyfile=keyfile, certfile=certfile)
            httpd.serve_forever()

        if server == 'waitress':
            """Start the server with the waitress server. Solid 'Production' WSGI server,
            no logging is set up.  Not the fastest server, but one of the most stable.
            """
            from waitress import serve
            print("Waitress serving on {}:{}".format(host, port))
            serve(self.wsgi, host=host, port=port, _quiet=self.quiet)
            
        if server == 'twisted':
            """Twisted server - a bit more complicated server.
            High performance for prodcution.  Supports SSL (if keyfile and certfile are set)
            """
            from twisted.web.server import Site
            from twisted.web.wsgi import WSGIResource
            from twisted.internet import reactor
            if not quiet:
                from twisted.python.log import startLogging
                import sys
                startLogging(sys.stdout)
            resource = WSGIResource(reactor, reactor.getThreadPool(), self.wsgi)
            site = Site(resource)
            if certfile:
                from twisted.internet import ssl
                sslContext = ssl.DefaultOpenSSLContextFactory(keyfile, certfile)
                reactor.listenSSL(port, site, sslContext)
            else:
                reactor.listenTCP(port, site)
            reactor.run()


    def route_by_name(self, route_name):
        """given a route_name, return the route"""
        for route, callback, methods, _name in self.routes:
            if route_name == _name:
                return route
        return None

    def url_for(self, route_name, **kwargs):
        """kwargs are NOT handled yet
        suppose a route /edit_page/<idx> ==> edit_page(env, idx), name="edit"
        url_for("edit", 22) ==> /edit_page/22
        """
        route = self.route_by_name(route_name)
        url = route_encode(route, **kwargs)
        return url

    def render_to_response(self, path_info):
        """render a path and its response to a three tuple
        (content, status_str, headers)
        """
        status_code = 200
        request_method = self.environ.get('REQUEST_METHOD')

        if not(self.routes):
            # IF NO ROUTES, then show server logo and exit
            response_body = "<pre>" + self.logo() + "</pre>"
            return Response(response_body).wsgi

        # handle static files
        if self.static_dir in path_info or 'favicon.ico' in path_info:
            # search the usual locations for our file, return if exists
            local_fname = search_file(path_info, self.app_dir, self.static_dir, self.template_dirs)

            # interpret response by filename extension
            if local_fname:
                # handle css and javascript status, headers
                if path_info.endswith('.css'):
                    response_body = get_text_file(path_info)
                    response = Response(response_body, 200, 'text/css')
                elif path_info.endswith('.js'):
                    response_body = get_text_file(path_info)
                    response = Response(response_body, 200, 'text/javascript')
                elif ext_check(path_info, self._graphic_types):
                    # image rendering short circuits below to return
                    response_body = get_file(path_info, ftype='binary')
                    # construct headers to contain expected image type, and cache
                    mimetype = mimeguess(path_info)
                    headers = [ ('Content-Type', mimetype), ('Cache-Control', 'public, max-age=43200') ]
                    response = Response(response_body, 200, headers)
                else:
                    # default html/text
                    response_body = get_text_file(path_info)
                    if response_body is None:
                        status_code = 404
                        response_body = self.not_found_html()
                    response = Response(response_body, status_code)
            else:
                # path_info file not found, respond 404
                response_body = self.not_found_html()
                response = Response(response_body, 404)

            # return the response to the WSGI server
            return response.wsgi

        ### Handle routes
        for route, handler, methods, _ in self.routes:
            # check for a route match and get any keyword arguments
            match, kwargs = route_match(route, path_info)
            # the path matches the route
            if match:
                # make sure METHODS are correct for the route
                if request_method in methods:
                    # get the handler/callback response
                    handler_response = handler(self.environ, **kwargs)
                    return Response(handler_response).wsgi
                else:
                    # return a 405 error, method not allowed.
                    response_body = '<h1>405 Method not allowed</h1>'
                    return Response(response_body, 405).wsgi

        # no matching route found, respond 404
        response_body = self.not_found_html()
        return Response(response_body, 404).wsgi


    def redirect(self, url, code=None):
        """redirects to url"""
        if not code:
            code = 303 if self.environ.get('SERVER_PROTOCOL') == "HTTP/1.1" else 302        
        headers = [("Location", url)]
        rstr = http.client.responses.get(code, 'UNKNOWN')
        status_str = f"{code} {rstr}"
        return "", status_str, headers

    def logo(self):
        """logo() - renders a simple text logo for the server"""
        year = datetime.datetime.now().year
        return _logo_text.format(year, _version_)

    def route(self, url, methods=None, route_name=None):
        """route decorator ala Flask and Bottle
        url is mandatory and follows route rules and var naming
        @app.route(/hello, methods=['GET'], name="hello")
        @app.route('/greet/<name>', name='greet_name')

        If name is NOT set, it defaults to None...
          instead, the route will look at the function it is wrapping
          then the name will be set to the function's __name__
        """
        def inner_decorator(f):
            nonlocal route_name
            # for some reason, have to trick python scope
            if route_name is None:
                route_name = f.__name__
            self.add_route(url, f, methods=methods, route_name=route_name)
            return f
        return inner_decorator
    
    def get(self, url, route_name=None):
        """route helper class GET method"""
        return self.route(url, methods=['GET'])
    def post(self, url, route_name=None):
        """route helper class POST method"""
        return self.route(url, methods=['POST'])
    def put(self, url, route_name=None):
        """route helper class PUT method"""
        return self.route(url, methods=['PUT'])
    def delete(self, url, route_name=None):
        """route helper class DELETE method"""
        return self.route(url, methods=['DELETE'])     

    def _jsonify(self, datadict):
        """
        Handle json.dumps errors
        """
        new_data = {}
        for k,v in datadict.items():
            try:
                item = json.dumps({k:v})
                new_data.update({k:v})
            except:
                if isinstance(v, dict):
                    # nested dictionary
                    try: 
                        udict = self._jsonify(v)
                        new_data.update({k:udict})
                    except:
                        new_data.update({k:"error"})
                else:
                    try:
                        new_data.update({k:str(v)})
                    except Exception as e:
                        new_data.update({k:f"Error - {e}"})
        
                
        return new_data
    
    def jsonify(self, datadict):
        """jsonify(self, datadict) - return the datadict as
        a JSON mimetype response
        """
        # encode and return JSON,
        try:
            response_body = json.dumps(datadict, skipkeys=True)
        except Exception as e:
            # this one can handle what json.dumps can't
            response_body = json.dumps(self._jsonify(datadict))
            
        headers = [('Content-Type', f'application/json;charset={self.charset}')]
        headers.append(('Content-Length', str(len(response_body))))
        return response_body, '200 OK', headers
    
    def before_request(self):
        """app before_request (WSGI) function wrapper"""
        def inner_decorator(f):
            self.app_before_request=f
            return f
        return inner_decorator
    
    def after_request(self):
        """app after_request (WSGI) function wrapper"""
        def inner_decorator(f):
            self.app_after_request=f
            return f
        return inner_decorator

#def app_middleware(self):
#        """app_middleware() - WSGI middleware function wrapper"""
#        def inner_decorator(f):
#            self.app_middleware=f
#            return f
#        return inner_decorator
    
    def template_filter(self, filter_name=None):
        """jinja template_filter decorator"""
        def inner_decorator(f):
            nonlocal filter_name
            if filter_name is None:
                filter_name = f.__name__
            self.template_filters[filter_name] = f
            return f
        return inner_decorator

    # config
    def config_from_file(self, config_file):
        """config from file"""
        with open(config_file) as fp:
            data = fp.read()
            
        lines = data.split('\n')
        for line in lines:
            parts = line.split('=')
            if len(parts) == 2:
                parts[0] = parts[0].strip()
                parts[1] = parts[1].strip()
                # strip off trailing and leading quotes
                if parts[1][0]  == '"' or parts[1][0] == "'":
                    parts[1] = parts[1][1:-1]
                self.config[parts[0].strip()] = parts[1]
                
    def get_cookies(self, environ):
        """ 
        app.cookies() - cookies are parsed into a MultDict (see below). 
        mostly used for enumeration cookies.
        
        A MultiDict allows a cookie name to be used twice
        """
        raw_cookies = environ.get('HTTP_COOKIE', '')
        cookies = SimpleCookie(raw_cookies).values()
        return MultiDict((c.key, c.value) for c in cookies)    
                
    def flash(self, *args, **kwargs):
        """
        flash(msg, [alert]) - for flashing messages that are available at
        the template level via get_flashed_messages() function.  Once a template reads
        them, these are discarded. Works by setting and unsetting a time stamped cookie.
        
        ex:
           flash("Hi there")
           flash("Yikes!", "danger")
        """
        name = _flash_cookie_prefix + str(time.time())
        msg = ''
        if len(args) == 1:
            msg = args[0] + _flashdelimiter
        else:
            msg = args[0] + _flashdelimiter + args[1]
            
        set_cookie(name, msg, days=1)
    
    def get_flashed_messages(self):
        """
        get_flashed_messages() - at the template, gets messages as a list if available and 
        returns these as a 2-tuple of message and alert level
        """
        messages = []
        cookies = get_cookies(self.environ)
        for cookie in cookies:
            for name, _ in cookie.items():
                if _flash_cookie_prefix in name:
                    # get the message
                    value = get_cookie(self.environ, name)
                    value = value.split(_flashdelimiter)
                    messages.append(value)
                    # now, set if to null and make the duration 0
                    set_cookie(name, '', days=0)
        return messages


def send_from_directory(filename, *args, **kwargs):
    """sends a file from directory(filename, args=list of directories to try, kwargs=keyword arguments)
    possible keyword arguments
    mimetype='image/png'
    ftype='binary'
    """
    response_body = get_file(filename, *args, **kwargs)
    if response_body:
        # set the mimetype
        if 'mimetype' in kwargs:
            mimetype = kwargs['mimetype']
        else:
            mimetype = mimeguess(filename)

        headers = [('Content-Type', mimetype), ('Cache-Control', 'public, max-age=43200')]
        if kwargs.get('as_attachment'):
            headers.append(('Content-Disposition', f'attachment; filename={filename}'))

        return Response(response_body, 200, headers)

    response_body = f'named resource not found: <b>{filename}</b>'
    status = 400

    return Response(response_body, status)


def render_template(filename, **kwargs):
    """render_template(filename, **kwargs
    provides flexible jinja2 rendering of filename and kwargs
    
    Args:
        filename - filename of template file, looks in candidate directories
        (by default, looking into ./templates but can be overridden with kwargs)
    """
    template_dirs = ''
    #static_dir =''
    if 'template_dirs' in kwargs:
        template_dirs = kwargs.get('template_dirs')
    #if 'static_dir' in kwargs:
    #    static_dir = kwargs.get('static_dir')
    if _template_dirs:
        # Minimus apps go this way, they will know the default template dir
        file_content = get_text_file(filename, _template_dirs, template_dirs)
        template_dirs = _template_dirs
    else:
        # non-Minimus users go this way
        #real_file = search_file(filename, *args)
        #template_dir = os.path.dirname(real_file)
        #file_content = get_text_file(filename, template_dir, static_dir)
        file_content = get_text_file(filename, template_dir)

    if file_content:
        # create a Jinja2 environment variable
        environment = Environment(loader=FileSystemLoader(template_dirs, followlinks=True))
        # process template filters from app if any
        for k,v in _app.template_filters.items():
            environment.filters[k] = v
        
        # inject 'g' global
        if kwargs.get('g') is None:
            # injecting g (global) object into the template
            kwargs['g'] = dict(g)
            
        # make url_for() function available at the template level
        kwargs['url_for'] = url_for
        
        # make get_flashed_messages available at template level
        kwargs['get_flashed_messages'] = get_flashed_messages
                
        template = environment.from_string(file_content)
        
        return template.render(**kwargs)
    return "ERROR: render_template - Failed to find {}".format(filename)

def render_html_file(filename, *args):
    """flexible straight HTML rendering of filename"""
    if _template_dirs:
        # Minimus apps use this route
        file_content = get_text_file(filename, _template_dirs, *args)
    else:
        # if a different call is made
        file_content = get_text_file(filename, *args)

    if file_content:
        return file_content
    else:
        return 'ERROR: render_html_file - Failed to find {}'.format(filename)

# Python 3 standard
from collections.abc import MutableMapping
class MultiDict(MutableMapping):

    """
    An ordered dictionary that can have multiple values for each key.
    Adds the methods getall, getone, mixed, and add to the normal
    dictionary interface.

    Class Attribution: BENJAMIN PETERSON and Miro HronÄ�ok (Python Paste) Thanks Ben and Miro!
    Only minor modifications were required.
    (https://github.com/cdent/paste/blob/master/paste/util/multidict.py)
    """

    def __init__(self, *args, **kw):
        if len(args) > 1:
            raise TypeError(
                "MultiDict can only be called with one positional argument")
        if args:
            if hasattr(args[0], 'iteritems'):
                items = args[0].iteritems()
            elif hasattr(args[0], 'items'):
                items = args[0].items()
            else:
                items = args[0]
            self._items = list(items)
        else:
            self._items = []
        # original code
        #self._items.extend(six.iteritems(kw))
        # modified code
        #self._items.extend(self._items.iter(items(**kw)))

    def __getitem__(self, key):
        for k, v in self._items:
            if k == key:
                return v
        raise KeyError(repr(key))

    def __setitem__(self, key, value):
        try:
            del self[key]
        except KeyError:
            pass
        self._items.append((key, value))

    def add(self, key, value):
        """
        Add the key and value, not overwriting any previous value.
        """
        self._items.append((key, value))

    def getall(self, key):
        """
        Return a list of all values matching the key (may be an empty list)
        """
        result = []
        for k, v in self._items:
            if type(key) == type(k) and key == k:
                result.append(v)
        return result

    def getone(self, key):
        """
        Get one value matching the key, raising a KeyError if multiple
        values were found.
        """
        v = self.getall(key)
        if not v:
            raise KeyError('Key not found: %r' % key)
        if len(v) > 1:
            raise KeyError('Multiple values match %r: %r' % (key, v))
        return v[0]

    def mixed(self):
        """
        Returns a dictionary where the values are either single
        values, or a list of values when a key/value appears more than
        once in this dictionary.  This is similar to the kind of
        dictionary often used to represent the variables in a web
        request.
        """
        result = {}
        multi = {}
        for key, value in self._items:
            if key in result:
                # We do this to not clobber any lists that are
                # *actual* values in this dictionary:
                if key in multi:
                    result[key].append(value)
                else:
                    result[key] = [result[key], value]
                    multi[key] = None
            else:
                result[key] = value
        return result

    def dict_of_lists(self):
        """
        Returns a dictionary where each key is associated with a
        list of values.
        """
        result = {}
        for key, value in self._items:
            if key in result:
                result[key].append(value)
            else:
                result[key] = [value]
        return result

    def __delitem__(self, key):
        items = self._items
        found = False
        for i in range(len(items)-1, -1, -1):
            if type(items[i][0]) == type(key) and items[i][0] == key:
                del items[i]
                found = True
        if not found:
            raise KeyError(repr(key))

    def __contains__(self, key):
        for k, v in self._items:
            if type(k) == type(key) and k == key:
                return True
        return False

    has_key = __contains__

    def clear(self):
        self._items = []

    def copy(self):
        return MultiDict(self)

    def setdefault(self, key, default=None):
        for k, v in self._items:
            if key == k:
                return v
        self._items.append((key, default))
        return default

    def pop(self, key, *args):
        if len(args) > 1:
            raise TypeError("pop expected at most 2 arguments, got "
                              + repr(1 + len(args)))
        for i in range(len(self._items)):
            if type(self._items[i][0]) == type(key) and self._items[i][0] == key:
                v = self._items[i][1]
                del self._items[i]
                return v
        if args:
            return args[0]
        else:
            raise KeyError(repr(key))

    def popitem(self):
        return self._items.pop()

    def update(self, other=None, **kwargs):
        if other is None:
            pass
        elif hasattr(other, 'items'):
            self._items.extend(other.items())
        elif hasattr(other, 'keys'):
            for k in other.keys():
                self._items.append((k, other[k]))
        else:
            for k, v in other:
                self._items.append((k, v))
        if kwargs:
            self.update(kwargs)

    def __repr__(self):
        items = ', '.join(['(%r, %r)' % v for v in self._items])
        return '%s([%s])' % (self.__class__.__name__, items)

    def __len__(self):
        return len(self._items)

    ##
    ## All the iteration:
    ##

    def keys(self):
        return [k for k, v in self._items]

    def iterkeys(self):
        for k, v in self._items:
            yield k

    __iter__ = iterkeys

    def items(self):
        return self._items[:]

    def iteritems(self):
        return iter(self._items)

    def values(self):
        return [v for k, v in self._items]

    def itervalues(self):
        for k, v in self._items:
            yield v

from urllib.parse import parse_qsl
def parse_querystring(environ):
    """
    Parses a query string into a list like ``[(name, value)]``.
    Caches this value in case parse_querystring is called again
    for the same request.
    You can pass the result to ``dict()``, but be aware that keys that
    appear multiple times will be lost (only the last value will be
    preserved).

    Function Attribution: BENJAMIN PETERSON and Miro HronÄ�ok (Python Paste)
    (https://github.com/cdent/paste/blob/master/paste/util/multidict.py)
    """
    source = environ.get('QUERY_STRING', '')
    if not source:
        return []
    if 'paste.parsed_querystring' in environ:
        parsed, check_source = environ['paste.parsed_querystring']
        if check_source == source:
            return parsed
    parsed = parse_qsl(source, keep_blank_values=True,
                       strict_parsing=False)
    environ['paste.parsed_querystring'] = (parsed, source)
    return parsed

def parse_querydict(environ):
    """
    Parses a query string into a python dict like ``{name: value}``.
    if multiple values are given for a key, the values are returned as a list
    like ``[value1, value2, ...]``.
    """
    d = {}
    for k, v in parse_querystring(environ):
        if k in d:
            if not isinstance(d[k], list):
                d[k] = [d[k]]
            d[k].append(v)
        else:
            d[k] = v

    return d

def parse_formvars(environ, include_get_vars=True, encoding=None, errors=None):
    """Parses the request, returning a MultiDict of form variables.
    If ``include_get_vars`` is true then GET (query string) variables
    will also be folded into the MultiDict.
    All values should be strings, except for file uploads which are
    left as ``FieldStorage`` instances.
    If the request was not a normal form request (e.g., a POST with an
    XML body) then ``environ['wsgi.input']`` won't be read.

    Function Attribution: BENJAMIN PETERSON and Miro HronÄ�ok (Python Paste)
    (https://github.com/cdent/paste/blob/master/paste/util/multidict.py)
    """
    source = environ['wsgi.input']
    if 'paste.parsed_formvars' in environ:
        parsed, check_source = environ['paste.parsed_formvars']
        if check_source == source:
            if include_get_vars:
                parsed.update(parse_querystring(environ))
            return parsed
    # @@: Shouldn't bother FieldStorage parsing during GET/HEAD and
    # fake_out_cgi requests
    formvars = MultiDict()
    ct = environ.get('CONTENT_TYPE', '').partition(';')[0].lower()
    use_cgi = ct in ('', 'application/x-www-form-urlencoded',
                                'multipart/form-data')
    # FieldStorage assumes a default CONTENT_LENGTH of -1, but a
    # default of 0 is better:
    if not environ.get('CONTENT_LENGTH'):
        environ['CONTENT_LENGTH'] = '0'
    if use_cgi:
        # Prevent FieldStorage from parsing QUERY_STRING during GET/HEAD
        # requests
        old_query_string = environ.get('QUERY_STRING','')
        environ['QUERY_STRING'] = ''
        inp = environ['wsgi.input']
        kwparms = {}
    
        if encoding:
            kwparms['encoding'] = encoding
        if errors:
            kwparms['errors'] = errors
        fs = cgi.FieldStorage(fp=inp,
                              environ=environ,
                              keep_blank_values=True,
                              **kwparms)
        environ['QUERY_STRING'] = old_query_string
        if isinstance(fs.value, list):
            for name in fs.keys():
                values = fs[name]
                if not isinstance(values, list):
                    values = [values]
                for value in values:
                    if not value.filename:
                        value = value.value
                    formvars.add(name, value)
    environ['paste.parsed_formvars'] = (formvars, source)
    if include_get_vars:
        formvars.update(parse_querystring(environ))
    return formvars

def parse_json(environ):
    """
    Parses a JSON request body into a python object.
    """
    # get the CONTENT_LENGTH
    try:
        request_body_size = int(environ.get('CONTENT_LENGTH', 0))
    except (ValueError):
        request_body_size = 0
        
    # get the content
    request_body = environ['wsgi.input'].read(request_body_size)
    
    # parse the content
    try:
        return json.loads(request_body)
    except:
        raise ValueError("Invalid JSON in request body")
        

# obscure.py
# these routines are meant to obscure data, not really encrypt it in a secure way.
# using a long random key really helps make this more secure
##################################################################
# functions to use are obscure, unobscure, encrypt, decrypt
# please use Python simple_crypt if you want true security
# all strings should be UTF-8 or an error will occur
# e.g. assuming you want UTF-8
# msg = b"Hello World"
# msg = "Hello World".encode('UTF-8')
# key = b'IamSekret'
# obscure(msg) => zlib_compressed_string
# unobscure(zlib_comressed_string) => msg
# encrypt(msg, key) => cipher
# decrypt(cipher, key) => msg
################################################################
import zlib
from base64 import urlsafe_b64encode as b64e, urlsafe_b64decode as b64d

def obscure(data: bytes) -> bytes:
    return b64e(zlib.compress(data, 9))

def unobscure(obscured: bytes) -> bytes:
    return zlib.decompress(b64d(obscured))

def xor_strings(s, t) -> bytes:
    """xor two strings together."""
    if isinstance(s, str):
        # Text strings contain single characters
        return b"".join(chr(ord(a) ^ ord(b)) for a, b in zip(s, t))
    else:
        # Python 3 bytes objects contain integer values in the range 0-255
        return bytes([a ^ b for a, b in zip(s, t)])

def __keypad(msg, key):
    """pad the key"""
    _key = key
    while len(_key) < len(msg):
        _key += _key
    return _key[:len(msg)]


def _encrypt(password, plaintext):
    """this is a workalike of simplecrypt.encrypt()
    It is only be used for non-critical security
    """
    _key = password
    if isinstance(password, str):
        _key = password.encode('UTF-8')
    if isinstance(plaintext, str):
        plaintext = plaintext.encode('UTF-8')
    _key = __keypad(plaintext, _key)
    cipher = xor_strings(plaintext, _key)
    ciphertext = obscure(cipher)
    return ciphertext

def _decrypt(password, ciphertext):
    """this is a workalike of simplecrypt.encrypt()
    It should only be used for non-critical security
    """
    _key = password
    if isinstance(password, str):
        _key = password.encode('UTF-8')
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode('UTF-8')
    _key = __keypad(ciphertext, _key)
    cipher = unobscure(ciphertext)
    decrypted = xor_strings(cipher, _key)
    return decrypted

def encrypt(password, plaintext, rounds=3):
    """encryption with rounds, rounds and password must match"""
    cipher_text = plaintext
    if rounds < 2:
         rounds = 2
    for _ in range(rounds):
        cipher_text = _encrypt(password, cipher_text)
    return cipher_text

def decrypt(password, ciphertext, rounds=3):
    """decryption with rounds, rounds and password must match"""
    if rounds < 2:
         rounds = 2
    plaintext = ciphertext
    for _ in range(rounds):
        try:
            plaintext = _decrypt(password, plaintext)
        except:
            return 'ERROR'
    return plaintext

def csrf_token(session:Session):
    """create a csrf_token and store in a session"""
    session.connect()
    token = token_generator(32, chars=string.ascii_letters + string.digits)
    session.data['csrf_token'] = token
    session.commit()
    return token

def validate_csrf(session:Session, csrf_token):
    """get the csrf_token from the session and compare the one from the form"""
    session.connect()
    if session.data.get('csrf_token') == csrf_token:
        return True
    return False

def flask_request(env):
    """adapter for wsgi flask-like request object"""
    request = JSObj()
    request.method = env['REQUEST_METHOD']
    request.form = parse_formvars(env)
    request.cookies = get_cookies(env)
    request.args = parse_querydict(env)
    request.path = env['PATH_INFO']
    request.is_json = request.path.endswith('.json')
    request.get_json = parse_json(env)
    request.url = env['wsgi.url_scheme'] + '://' + env['HTTP_HOST'] + env['PATH_INFO'] + "?" + env['QUERY_STRING']
    return request

if __name__ == '__main__':
    mini = Minimus('__main__')
    print(mini.logo())
    print("Minimus is a web framework for Python 3.6+")
