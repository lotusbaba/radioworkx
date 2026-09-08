import sys
from app import db
from app.catalog import import_catalog

db.init()
print(f'Imported {import_catalog(sys.argv[1])} tracks')
