"""Idempotent column-level migrations for existing databases; fresh databases get everything from metadata create_all."""
from sqlalchemy import inspect,text
from src.config.database import engine
COLUMNS={'traces':{'evidence':'JSON'}}
def migrate():
 with engine.begin() as c:
  for table,columns in COLUMNS.items():
   existing={col['name'] for col in inspect(c).get_columns(table)}
   for name,ddl in columns.items():
    if name not in existing:c.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
