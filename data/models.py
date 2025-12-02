# data/models.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from data.database import Base
import json

class ApiLink(Base):
    __tablename__ = 'api_links'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    url = Column(String)  # Основной URL (для обратной совместимости)
    api_urls = Column(Text, default='[]')  # JSON массив API URL
    html_urls = Column(Text, default='[]')  # JSON массив HTML URL
    exchange = Column(String)
    check_interval = Column(Integer, default=300)
    is_active = Column(Boolean, default=True)
    added_by = Column(Integer)
    last_checked = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    def get_api_urls(self):
        """Получить список API URL"""
        try:
            urls = json.loads(self.api_urls) if self.api_urls else []
            return urls if urls else []
        except:
            return []

    def set_api_urls(self, urls):
        """Установить список API URL"""
        self.api_urls = json.dumps(urls) if urls else '[]'

    def get_html_urls(self):
        """Получить список HTML URL"""
        try:
            urls = json.loads(self.html_urls) if self.html_urls else []
            return urls if urls else []
        except:
            return []

    def set_html_urls(self, urls):
        """Установить список HTML URL"""
        self.html_urls = json.dumps(urls) if urls else '[]'

    def get_all_urls(self):
        """Получить все URL (API + HTML)"""
        return {
            'api': self.get_api_urls(),
            'html': self.get_html_urls()
        }

class PromoHistory(Base):
    __tablename__ = 'promo_history'
    
    id = Column(Integer, primary_key=True)
    api_link_id = Column(Integer, ForeignKey('api_links.id'))
    promo_id = Column(String)
    exchange = Column(String)
    title = Column(String)
    description = Column(Text)
    total_prize_pool = Column(String)
    award_token = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    link = Column(String)
    icon = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    api_link = relationship("ApiLink", backref="promos")

class ProxyServer(Base):
    __tablename__ = 'proxy_servers'
    
    id = Column(Integer, primary_key=True)
    address = Column(String, unique=True)
    protocol = Column(String)
    status = Column(String, default="testing")
    speed_ms = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    priority = Column(Integer, default=5)
    last_used = Column(DateTime)
    last_success = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime)

class UserAgent(Base):
    __tablename__ = 'user_agents'
    
    id = Column(Integer, primary_key=True)
    user_agent_string = Column(String, unique=True)
    browser_type = Column(String)
    browser_version = Column(String)
    platform = Column(String)
    device_type = Column(String)
    status = Column(String, default="active")
    usage_count = Column(Integer, default=0)
    success_rate = Column(Float, default=0.0)
    last_used = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime)

class RotationStats(Base):
    __tablename__ = 'rotation_stats'
    
    id = Column(Integer, primary_key=True)
    proxy_id = Column(Integer, ForeignKey('proxy_servers.id'))
    user_agent_id = Column(Integer, ForeignKey('user_agents.id'))
    exchange = Column(String)
    request_result = Column(String)
    response_code = Column(Integer)
    response_time_ms = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    proxy = relationship("ProxyServer", backref="stats")
    user_agent = relationship("UserAgent", backref="stats")

class AggregatedStats(Base):
    __tablename__ = 'aggregated_stats'
    
    id = Column(Integer, primary_key=True)
    date = Column(DateTime)
    exchange = Column(String)
    total_requests = Column(Integer, default=0)
    successful_requests = Column(Integer, default=0)
    blocked_requests = Column(Integer, default=0)
    average_response_time = Column(Float, default=0.0)
    best_proxy_id = Column(Integer, ForeignKey('proxy_servers.id'))
    best_user_agent_id = Column(Integer, ForeignKey('user_agents.id'))
    
    best_proxy = relationship("ProxyServer", foreign_keys=[best_proxy_id])
    best_user_agent = relationship("UserAgent", foreign_keys=[best_user_agent_id])

class RotationSettings(Base):
    __tablename__ = 'rotation_settings'
    
    id = Column(Integer, primary_key=True)
    rotation_interval = Column(Integer, default=1800)
    auto_optimize = Column(Boolean, default=True)
    stats_retention_days = Column(Integer, default=90)
    archive_inactive_days = Column(Integer, default=30)
    last_rotation = Column(DateTime)
    last_cleanup = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)