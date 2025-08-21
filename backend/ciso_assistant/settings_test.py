from .settings import *

# Override database settings for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'test_ciso_assistant_db',      # Change to your test DB name
        'USER': 'test_db_user',                # Change to your test DB user
        'PASSWORD': 'test_db_password',        # Change to your test DB password
        'HOST': 'localhost',
        'PORT': '5432',
        'TEST': {
            'NAME': 'test_ciso_assistant_db',  # Ensures Django uses this for test DB
        },
    }
}

# Optional: Speed up tests by using a faster password hasher
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Optional: Disable email sending during tests
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Optional: Other test-specific settings