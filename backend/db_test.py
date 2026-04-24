from sqlalchemy import create_engine

DATABASE_URL = "postgresql+psycopg2://postgres.sucirwpwuhvlxydrwrhy:MDegree%409356DO@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres"

engine = create_engine(
    DATABASE_URL,
    connect_args={"sslmode": "require"}  # important for Supabase
)

try:
    with engine.connect() as conn:
        print("✅ Connected to MicroDegree DB")
except Exception as e:
    print("❌ Connection failed:", e)