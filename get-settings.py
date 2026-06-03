from instagrapi import Client

c = Client()

username = input("Username: ")
password = input("Password: ")
two_fa_code= input("2FA code: ")

c.login(username, password, False, two_fa_code)
c.dump_settings('./settings.json')

print("--- End of Program ---") 
