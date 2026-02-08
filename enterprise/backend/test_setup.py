import os
import sys
import django
from pathlib import Path

# Add the backend paths to Python path
backend_path = Path(__file__).parent.parent.parent / 'backend'
enterprise_path = Path(__file__).parent

sys.path.insert(0, str(backend_path))
sys.path.insert(0, str(enterprise_path))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'enterprise_core.settings')

try:
    django.setup()
    print("✓ Django setup successful!")
    
    # Test database connection
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        print("✓ Database connection successful!")
        
    # Test if we can import WSGI application
    from enterprise_core.wsgi import application
    print("✓ WSGI application import successful!")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
