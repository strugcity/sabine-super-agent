#!/usr/bin/env python3
"""
Railway Deployment Verification Script

This script verifies that sabine_v1 is properly deployed and functioning on Railway.
It checks health endpoints, tool loading, and basic functionality.

Usage:
    python scripts/verify_railway_deployment.py [URL]
    
If URL is not provided, it will try common Railway URL patterns.
"""

import requests
import json
import sys
import time
from typing import Optional, Dict, Any


def check_health(base_url: str) -> Optional[Dict[str, Any]]:
    """Check the /health endpoint."""
    try:
        response = requests.get(f"{base_url}/health", timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Health check failed: HTTP {response.status_code}")
            return None
    except requests.exceptions.Timeout:
        print(f"⏰ Health check timed out (30s)")
        return None
    except requests.exceptions.ConnectionError:
        print(f"❌ Connection failed")
        return None
    except Exception as e:
        print(f"❌ Health check error: {str(e)}")
        return None


def check_tools(base_url: str) -> Optional[Dict[str, Any]]:
    """Check the /tools endpoint."""
    try:
        response = requests.get(f"{base_url}/tools", timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Tools check failed: HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Tools check error: {str(e)}")
        return None


def check_root(base_url: str) -> Optional[Dict[str, Any]]:
    """Check the root endpoint for API info."""
    try:
        response = requests.get(base_url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None


def check_mcp_diagnostics(base_url: str) -> Optional[Dict[str, Any]]:
    """Check MCP server diagnostics."""
    try:
        response = requests.get(f"{base_url}/tools/diagnostics", timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None


def verify_deployment(base_url: str) -> bool:
    """Comprehensive deployment verification."""
    print(f"🔍 Verifying deployment at: {base_url}")
    print("=" * 60)
    
    success = True
    
    # 1. Health Check
    print("1. Health Check...")
    health_data = check_health(base_url)
    if health_data:
        print(f"   ✅ Status: {health_data.get('status', 'unknown')}")
        print(f"   ✅ Version: {health_data.get('version', 'unknown')}")
        print(f"   ✅ Tools loaded: {health_data.get('tools_loaded', 0)}")
        print(f"   ✅ Database connected: {health_data.get('database_connected', False)}")
    else:
        print("   ❌ Health check failed")
        success = False
    
    print()
    
    # 2. API Info
    print("2. API Information...")
    root_data = check_root(base_url)
    if root_data:
        print(f"   ✅ Name: {root_data.get('name', 'unknown')}")
        print(f"   ✅ Status: {root_data.get('status', 'unknown')}")
        endpoints = root_data.get('endpoints', {})
        print(f"   ✅ Endpoints: {len(endpoints)} available")
        for endpoint, desc in list(endpoints.items())[:5]:  # Show first 5
            print(f"      - {endpoint}")
    else:
        print("   ⚠️  API info not available")
    
    print()
    
    # 3. Tools Loading
    print("3. Tools Loading...")
    tools_data = check_tools(base_url)
    if tools_data and tools_data.get('success'):
        tool_count = tools_data.get('count', 0)
        print(f"   ✅ {tool_count} tools loaded successfully")
        
        # Show some tool names
        tools = tools_data.get('tools', [])[:5]  # First 5 tools
        for tool in tools:
            print(f"      - {tool.get('name', 'unknown')}")
        if len(tools_data.get('tools', [])) > 5:
            print(f"      ... and {len(tools_data.get('tools', [])) - 5} more")
    else:
        print("   ❌ Tools loading failed")
        success = False
    
    print()
    
    # 4. MCP Diagnostics
    print("4. MCP Server Diagnostics...")
    mcp_data = check_mcp_diagnostics(base_url)
    if mcp_data:
        if mcp_data.get('success'):
            print("   ✅ MCP diagnostics successful")
            print(f"   ✅ GitHub token set: {mcp_data.get('github_token_set', False)}")
            
            # Show server status if available
            servers = mcp_data.get('servers', {})
            for server_name, server_info in servers.items():
                status = server_info.get('status', 'unknown')
                tools_count = len(server_info.get('tools', []))
                print(f"      - {server_name}: {status} ({tools_count} tools)")
        else:
            print(f"   ⚠️  MCP diagnostics failed: {mcp_data.get('error', 'unknown')}")
    else:
        print("   ⚠️  MCP diagnostics not available")
    
    print()
    print("=" * 60)
    
    if success:
        print("🎉 DEPLOYMENT VERIFICATION SUCCESSFUL!")
        print(f"🌐 Active URL: {base_url}")
        print("\n✅ sabine_v1 is functioning properly on Railway")
    else:
        print("🚨 DEPLOYMENT VERIFICATION FAILED!")
        print("❌ sabine_v1 has issues that need to be resolved")
    
    return success


def main():
    """Main verification function."""
    print("🚀 SABINE V1 RAILWAY DEPLOYMENT VERIFICATION")
    print("=" * 60)
    
    # Get URL from command line or try common patterns
    if len(sys.argv) > 1:
        urls_to_try = [sys.argv[1]]
    else:
        print("🔍 No URL provided, trying common Railway patterns...")
        urls_to_try = [
            "https://sabine-super-agent-production.up.railway.app",
            "https://sabine-super-agent.up.railway.app",
            "https://sabine-v1.up.railway.app",
            "https://web-production-1234.up.railway.app",  # Generic pattern
        ]
    
    success = False
    
    for url in urls_to_try:
        print(f"\n🌐 Trying: {url}")
        
        # Quick connectivity test first
        try:
            response = requests.get(url, timeout=5)
            if response.status_code in [200, 404]:  # 404 is better than timeout
                print("   ✅ Server responding")
                if verify_deployment(url):
                    success = True
                    break
            else:
                print(f"   ❌ HTTP {response.status_code}")
        except requests.exceptions.Timeout:
            print("   ⏰ Connection timeout")
        except requests.exceptions.ConnectionError:
            print("   ❌ Connection failed")
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
    
    if not success:
        print("\n" + "=" * 60)
        print("🚨 NO WORKING DEPLOYMENT FOUND")
        print("\n📋 Next Steps:")
        print("1. Check Railway dashboard for deployment status")
        print("2. Look for build/runtime errors in Railway logs")
        print("3. Verify environment variables are set")
        print("4. Check if service is running but on different URL")
        print("5. Trigger manual redeploy if needed")
        
        print("\n🔧 Common Issues:")
        print("- Environment variables missing (ANTHROPIC_API_KEY, etc.)")
        print("- Build failing due to dependency issues")
        print("- Supervisor not starting services properly")
        print("- Port binding issues (Railway sets PORT env var)")
        print("- MCP server credential setup failures")
        
        sys.exit(1)
    
    print("\n🎯 Verification complete!")


if __name__ == "__main__":
    main()