from sqlalchemy import create_engine, text
engine = create_engine("postgresql+psycopg2://postgres:pramanik@localhost:5433/pramanikh")
with engine.connect() as c:
    print(c.execute(text("select 1")).scalar())