from django.urls import include, path
from . import views


app_name = "chat"
api_patterns = [
    path("", views.chat, name="send"),
    path("conversations/delete/", views.delete_chats, name="delete-chats"),
    path("conversations/", views.chat_conversations, name="conversations"),
    path("conversations/<uuid:conversation_id>/", views.chat_conversation_detail, name="conversation-detail"),
    path("compact/", views.compact_context, name="compact-context"),
    path("account-memory/", views.account_memory, name="account-memory"),
    path("memory/", views.chat_memory_preference, name="memory-preference"),
    path("memories/", views.chat_memories, name="memories"),
    path("memories/<int:memory_id>/", views.chat_memory_detail, name="memory-detail"),
    path("markdown/", views.render_markdown, name="markdown"),
]
urlpatterns = [
    path("_chat/", views.chat_page, name="chat"),
    path("chat/", views.chat_page, name="chat-alias"),
    path("api/chat/", include(api_patterns)),
    path("api/", include(api_patterns)),
]
