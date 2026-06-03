"""
Monkey patch for instagrapi 2.2.1 to fix multiple bugs:

1. extract_user_gql() TypeError - update_headers argument doesn't exist
2. KeyError: 'pinned_channels_info' - missing key in user data
3. Pydantic ValidationError: bio_links.0.link_id - missing required field

Issue: instagrapi 2.2.1 bugs in extract_user_gql() and extract_broadcast_channel()
"""

# Track if patch has been applied to avoid double-patching
_patch_applied = False


def patch_instagrapi():
    """
    Apply monkey patch to fix extract_user_gql() TypeError in instagrapi 2.2.1
    """
    global _patch_applied
    
    if _patch_applied:
        return True
    
    try:
        from instagrapi.mixins.user import UserMixin
        import json
        
        # Check if already patched by checking if method has our marker
        if hasattr(UserMixin.user_info_by_username_gql, '_instagrapi_patched'):
            _patch_applied = True
            return True
        
        # Store original method
        original_user_info_by_username_gql = UserMixin.user_info_by_username_gql
        
        def patched_user_info_by_username_gql(self, username: str):
            """
            Patched version that removes the update_headers argument
            """
            username = str(username).lower()
            temporary_public_headers = {
                'Host': 'www.instagram.com',
                'X-Requested-With': 'XMLHttpRequest',
                'Sec-Ch-Prefers-Color-Scheme': 'dark',
                'Sec-Ch-Ua-Platform': '"Linux"',
                'X-Ig-App-Id': '936619743392459',
                'Sec-Ch-Ua-Model': '""',
                'Sec-Ch-Ua-Mobile': '?0',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.112 Safari/537.36',
                'Accept': '*/*',
                'X-Asbd-Id': '129477',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': 'https://www.instagram.com/',
                'Accept-Language': 'en-US,en;q=0.9',
                'Priority': 'u=1, i'
            }
            
                # Fixed: Remove update_headers argument and handle pinned_channels_info KeyError
            from instagrapi.extractors import extract_user_gql, extract_broadcast_channel
            import instagrapi.extractors
            
            # Patch extract_broadcast_channel to handle missing pinned_channels_info
            original_extract_broadcast_channel = extract_broadcast_channel
            
            def patched_extract_broadcast_channel(data):
                """Patched version that handles missing pinned_channels_info"""
                try:
                    # Check if pinned_channels_info exists
                    if "pinned_channels_info" not in data:
                        return []
                    if "pinned_channels_list" not in data.get("pinned_channels_info", {}):
                        return []
                    return original_extract_broadcast_channel(data)
                except KeyError as e:
                    if 'pinned_channels_info' in str(e) or 'pinned_channels_list' in str(e):
                        # Return empty list if pinned_channels_info is missing
                        return []
                    raise
            
            # Patch extract_user_gql to handle missing broadcast_channel
            original_extract_user_gql = extract_user_gql
            
            def patched_extract_user_gql(data):
                """Patched version that handles missing broadcast_channel and bio_links validation errors"""
                try:
                    # Try to extract broadcast_channel, but handle KeyError gracefully
                    if "pinned_channels_info" in data:
                        data["broadcast_channel"] = patched_extract_broadcast_channel(data)
                    else:
                        data["broadcast_channel"] = []
                except Exception:
                    # If anything fails, set to empty list
                    data["broadcast_channel"] = []
                
                # Fix bio_links validation error - filter out links without link_id
                if "bio_links" in data and isinstance(data["bio_links"], list):
                    data["bio_links"] = [
                        link for link in data["bio_links"]
                        if isinstance(link, dict) and "link_id" in link
                    ]
                
                # Continue with original extract_user_gql logic (matching actual implementation)
                from instagrapi.types import User
                return User(
                    pk=data["id"],
                    media_count=data.get("edge_owner_to_timeline_media", {}).get("count", 0),
                    follower_count=data.get("edge_followed_by", {}).get("count", 0),
                    following_count=data.get("edge_follow", {}).get("count", 0),
                    is_business=data.get("is_business_account", False),
                    public_email=data.get("business_email"),
                    contact_phone_number=data.get("business_phone_number"),
                    **data  # Pass all other data fields
                )
            
            # Temporarily replace the functions
            instagrapi.extractors.extract_broadcast_channel = patched_extract_broadcast_channel
            instagrapi.extractors.extract_user_gql = patched_extract_user_gql
            
            try:
                response = self.public_request(
                    f'https://www.instagram.com/api/v1/users/web_profile_info/?username={username}',
                    headers=temporary_public_headers
                )
                data = patched_extract_user_gql(json.loads(response)['data']['user'])
                return data
            finally:
                # Restore original functions
                instagrapi.extractors.extract_broadcast_channel = original_extract_broadcast_channel
                instagrapi.extractors.extract_user_gql = original_extract_user_gql
        
        # Mark as patched
        patched_user_info_by_username_gql._instagrapi_patched = True
        
        # Apply the patch
        UserMixin.user_info_by_username_gql = patched_user_info_by_username_gql
        _patch_applied = True
        print("✅ Applied instagrapi patch for extract_user_gql() TypeError")
        return True
        
    except Exception as e:
        print(f"⚠️ Failed to apply instagrapi patch: {e}")
        import traceback
        traceback.print_exc()
        return False


# Auto-apply patch on import
if __name__ != "__main__":
    try:
        patch_instagrapi()
    except Exception:
        # Silently fail if instagrapi is not available
        pass

