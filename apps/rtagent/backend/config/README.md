# Configuration Structure

This directory contains the **configuration system** for the real-time voice agent.

## 📁 File Structure

```
config/
├── __init__.py           # Main exports and config management
├── app_settings.py       # Application behavior settings (env vars)
├── infrastructure.py     # Azure services configuration (secrets)
├── constants.py          # Hard-coded constants and defaults
├── app_config.py         # Structured dataclass configurations
└── README.md            # This file
```

## 🎯 Configuration Philosophy

### **Clear Separation of Concerns**

1. **`infrastructure.py`** - Azure services, secrets, endpoints
   - Connection strings, service keys, resource IDs
   - All secrets loaded from environment variables
   - Infrastructure-level settings that rarely change

2. **`app_settings.py`** - Application behavior and performance
   - Pool sizes, timeouts, feature flags
   - User-configurable application behavior
   - Performance tuning parameters

3. **`constants.py`** - Hard-coded constants
   - API endpoints, supported languages
   - Default values and available options
   - Non-configurable application constants

4. **`app_config.py`** - Structured configuration objects
   - Type-safe dataclass configurations
   - Validation and serialization support
   - Easy access to grouped settings