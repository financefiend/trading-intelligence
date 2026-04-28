
import pandas as pd
from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv()

sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

r = sb.table('index_composition').select('symbol,company_name,effective_from,effective_to,is_current').eq('index_name', 'NIFTY 500').execute()

df = pd.DataFrame(r.data)
df.to_csv('nifty500_current_db.csv', index=False)
print(f'Exported {len(df)} stocks to nifty500_current_db.csv')
