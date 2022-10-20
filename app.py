from minimus import Minimus, Session
from minimus_admin import Admin
import sys

app = Minimus(__name__)
session = Session(app)
admin = Admin(app, session)

# bootstrap the admin, once created you can add models and edit the admin
admin.create_user("admin", "changethis!")

@app.route("/")
def index(env):
    return """
<h1>Minimus App</h1>
Barebones Minimus app with admin.<br>
Admin: <a href="/admin">/admin</a><br>
"""

# gunicorn mount, just in case
wsgi = app.wsgi

if __name__ == '__main__':
    app.run()