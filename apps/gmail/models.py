from django.db import models
#from datetime import datetime
#from django.contrib.auth.models import User 
# Create your models here.
'''
class GoogleCredential(models.Model):
    """Google OAuth credentials storage"""
    #__tablename__ = 'google_credentials'
    
    id = models.IntegerField(primary_key=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE ,null=False)
    name = models.CharField(max_length =100, null=False)
    client_id = models.CharField(max_length =255, null=False)
    client_secret = models.CharField(max_length =255, null=False)
    access_token = models.CharField()
    refresh_token = models.CharField()
    token_expiry = models.DateTimeField()
    is_authenticated = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(default=datetime.utcnow)
    
    def __str__(self):
        return f'<GoogleCredential {self.name}>'

'''
