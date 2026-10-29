import json
from io import BytesIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from organizations.models import Organization, OrganizationMembership
from ai_gateway.models import AIConfiguration
from .models import AccountAIMemory, ChatConversation, ChatMessage
from .context_management import update_account_memory


class ContextManagementTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('context-owner')
        self.other = get_user_model().objects.create_user('context-other')
        self.org = Organization.objects.create(name='Neutral workspace')
        OrganizationMembership.objects.create(organization=self.org, user=self.user, role='manager')
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role='member')
        self.client.force_login(self.user)
        self.conversation = ChatConversation.objects.create(account=self.user, organization=self.org, owner_hash=ChatConversation.hash_owner(f'orgforms:{self.user.pk}:{self.org.pk}'), model='test-model')
        ChatMessage.objects.bulk_create([ChatMessage(conversation=self.conversation, role='user' if i % 2 == 0 else 'assistant', content=f'Message {i}. ' + 'Long conversation detail. ' * 80) for i in range(10)])

    def compact(self):
        return self.client.post('/api/chat/compact/', {'organization_slug':self.org.slug, 'conversation_id':str(self.conversation.pk)}, format='json')

    def test_compaction_reduces_context_and_preserves_transcript(self):
        result = self.compact()
        self.assertEqual(result.status_code, 200)
        self.assertLess(result.data['characters_after'], result.data['characters_before'])
        self.assertEqual(self.conversation.messages.count(), 10)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.compacted_message_count, 6)
        self.assertIn('Earlier chat excerpts', self.conversation.context_summary)
        self.assertEqual(self.compact().status_code, 400)

    def test_other_member_cannot_compact_my_chat(self):
        self.client.force_login(self.other)
        self.assertEqual(self.compact().status_code, 404)

    @patch('chat.views.open_model_response')
    def test_next_request_uses_digest_and_recent_turns(self, upstream):
        self.compact()
        upstream.return_value = BytesIO(b'{"message":{"content":"Reply"},"done":true}\n')
        result = self.client.post('/api/chat/', {'organization_slug':self.org.slug, 'conversation_id':str(self.conversation.pk), 'model':'test-model', 'messages':[{'role':'user','content':'Next question'}], 'context_options':{'organization':False,'documents':False,'saved_memory':False}}, format='json')
        self.assertEqual(result.status_code, 200)
        b''.join(result.streaming_content)
        sent = upstream.call_args.args[1]['messages']
        self.assertEqual(len(sent), 6)  # digest + four recent + new prompt
        self.assertIn('<earlier_chat>', sent[0]['content'])
        self.assertTrue(sent[1]['content'].startswith('Message 6.'))
        self.assertEqual(sent[-1]['content'], 'Next question')
        self.assertEqual(self.conversation.messages.count(), 12)

    def test_temporary_compaction_does_not_save_a_conversation(self):
        count = ChatConversation.objects.count()
        result = self.client.post('/api/chat/compact/', {'messages':[{'role':'user','content':'x' * 2000} for _ in range(6)]}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(ChatConversation.objects.count(), count)

    def test_account_notes_private_and_edits_have_revision_checks(self):
        result = self.client.patch('/api/chat/account-memory/', {'revision':0,'content':'I prefer concise replies.', 'use_enabled':True}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.patch('/api/chat/account-memory/', {'revision':0,'content':'Stale edit'}, format='json').status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/chat/account-memory/').data['content'], '')
        self.client.logout()
        self.assertIn(self.client.get('/api/chat/account-memory/').status_code, (401,403))

    @patch('chat.views.open_model_response')
    def test_account_notes_used_only_when_selected_and_never_in_temporary_chats(self, upstream):
        AccountAIMemory.objects.create(account=self.user, content='Prefers concise replies.', use_enabled=True)
        for temporary, selected, expected in [(False,True,True),(False,False,False),(True,True,False)]:
            upstream.return_value = BytesIO(b'{"message":{"content":"Reply"},"done":true}\n')
            result = self.client.post('/api/chat/', {'organization_slug':self.org.slug, 'temporary':temporary,'model':'test-model','messages':[{'role':'user','content':'Hi'}], 'context_options':{'organization':False,'documents':False,'saved_memory':False,'account_memory':selected}}, format='json')
            self.assertEqual(result.status_code, 200)
            b''.join(result.streaming_content)
            sent = upstream.call_args.args[1]['messages']
            self.assertEqual(any('<account_notes>' in m['content'] for m in sent), expected)

    def test_auto_update_uses_user_statements_and_cannot_overwrite_newer_edit(self):
        memory = AccountAIMemory.objects.create(account=self.user, auto_update=True, content='Old notes')
        ChatMessage.objects.create(conversation=self.conversation, role='user', content='I prefer brief replies.\n\nAttached text files:\nPRIVATE FILE CONTENT')
        captured = []
        def response(profile, payload):
            captured.append(payload)
            AccountAIMemory.objects.filter(pk=memory.pk).update(content='Manual edit', revision=1)
            return BytesIO(json.dumps({'message':{'content':json.dumps({'content':'Extracted notes'})}}).encode())
        update_account_memory(self.conversation, response, AIConfiguration.get_or_create_default())
        memory.refresh_from_db()
        self.assertEqual(memory.content, 'Manual edit')
        source = json.loads(captured[0]['messages'][1]['content'])['user_statements']
        self.assertTrue(all('PRIVATE FILE CONTENT' not in text for text in source))
        self.assertTrue(all(not text.startswith('Message 9.') for text in source))

    def test_auto_update_requires_opt_in(self):
        with patch('chat.views.open_model_response') as upstream:
            update_account_memory(self.conversation, upstream, AIConfiguration.get_or_create_default())
            upstream.assert_not_called()

    def test_auto_update_refreshes_the_same_account_notes(self):
        memory = AccountAIMemory.objects.create(account=self.user, auto_update=True, content='Old notes')
        def response(profile, payload):
            return BytesIO(json.dumps({'message':{'content':json.dumps({'content':'Prefers short replies.'})}}).encode())
        update_account_memory(self.conversation, response, AIConfiguration.get_or_create_default())
        memory.refresh_from_db()
        self.assertEqual(memory.content, 'Prefers short replies.')
        self.assertEqual(memory.revision, 1)
        self.assertEqual(AccountAIMemory.objects.filter(account=self.user).count(), 1)


class DeleteChatTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('delete-owner')
        self.other = get_user_model().objects.create_user('delete-other')
        self.org = Organization.objects.create(name='Chat workspace')
        for user in (self.user,self.other):
            OrganizationMembership.objects.create(organization=self.org,user=user,role='member')
        self.client.force_login(self.user)
        self.chats = [ChatConversation.objects.create(organization=self.org,account=self.user,owner_hash=ChatConversation.hash_owner(f'orgforms:{self.user.pk}:{self.org.pk}')) for _ in range(2)]
        self.foreign = ChatConversation.objects.create(organization=self.org,account=self.other,owner_hash=ChatConversation.hash_owner(f'orgforms:{self.other.pk}:{self.org.pk}'))

    def delete(self, ids):
        return self.client.post('/api/chat/conversations/delete/', {'organization_slug':self.org.slug,'conversation_ids':[str(id) for id in ids]},format='json')

    def test_bulk_delete_removes_messages_but_keeps_memory(self):
        from .models import ChatMemory
        message = ChatMessage.objects.create(conversation=self.chats[0],role='user',content='Test message')
        note = ChatMemory.objects.create(owner_hash=self.chats[0].owner_hash,content='Saved note',source_conversation=self.chats[0])
        AccountAIMemory.objects.create(account=self.user,content='Account note')
        result = self.delete([chat.pk for chat in self.chats])
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.data['deleted'],2)
        self.assertFalse(ChatMessage.objects.filter(pk=message.pk).exists())
        self.assertTrue(ChatConversation.objects.filter(pk=self.foreign.pk).exists())
        note.refresh_from_db()
        self.assertIsNone(note.source_conversation_id)
        self.assertEqual(AccountAIMemory.objects.get(account=self.user).content,'Account note')

    def test_mixed_unauthorized_batch_deletes_nothing(self):
        result = self.delete([self.chats[0].pk,self.foreign.pk])
        self.assertEqual(result.status_code,404)
        self.assertEqual(ChatConversation.objects.count(),3)

    def test_empty_invalid_and_duplicate_ids(self):
        self.assertEqual(self.delete([]).status_code,400)
        self.assertEqual(self.delete(['invalid']).status_code,400)
        self.assertEqual(self.delete([self.chats[0].pk,self.chats[0].pk]).data['deleted'],1)

    def test_late_reply_does_not_recreate_a_deleted_chat(self):
        from .views import _persist_assistant_message
        conversation_id = self.chats[0].pk
        self.delete([conversation_id])
        _persist_assistant_message(conversation_id, 'Late reply')
        self.assertFalse(ChatMessage.objects.filter(conversation_id=conversation_id).exists())
