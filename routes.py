import supabase
from supabase import create_client
from dotenv import load_dotenv

import os

load_dotenv()

# Supabase setup
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

print(supabase_key)
print(supabase_url)
