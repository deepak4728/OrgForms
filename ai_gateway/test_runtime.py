import json
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from organizations.models import Organization, OrganizationMembership
from .runtime import RuntimeErrorDetail, local_endpoint, change_server, running_models


class RuntimeEndpointTests(TestCase):
    def setUp(self):
        self.owner=get_user_model().objects.create_user('runtime-owner')
        self.member=get_user_model().objects.create_user('runtime-member')
        self.other=get_user_model().objects.create_user('runtime-other')
        self.org=Organization.objects.create(name='Runtime workspace',created_by=self.owner)
        OrganizationMembership.objects.create(organization=self.org,user=self.owner,role='admin')
        OrganizationMembership.objects.create(organization=self.org,user=self.member,role='member')
        self.client.force_login(self.owner)
        self.server=reverse('ai_gateway:ollama-server')+'?org='+self.org.slug
        self.ps=reverse('ai_gateway:ollama-ps')+'?org='+self.org.slug

    @patch('ai_gateway.runtime.server_status',return_value={'running':False,'managed':False,'installed':True})
    def test_local_admin_can_read_server_state(self,service):
        result=self.client.get(self.server)
        self.assertEqual(result.status_code,200);self.assertTrue(result.json()['can_control'])

    @patch('ai_gateway.runtime.change_server',return_value={'running':True,'managed':True,'installed':True})
    def test_local_admin_can_start_server(self,service):
        result=self.client.post(self.server,json.dumps({'action':'start'}),content_type='application/json')
        self.assertEqual(result.status_code,200);service.assert_called_once_with('start')

    @patch('ai_gateway.runtime.change_server',return_value={'running':True,'managed':True,'installed':True})
    @patch('ai_gateway.runtime.server_status',return_value={'running':False,'managed':False,'installed':True})
    def test_manager_can_read_and_control_local_server(self,status,command):
        self.org.memberships.filter(user=self.owner).update(role='manager')
        response=self.client.get(self.server)
        self.assertTrue(response.json()['can_control'])
        for action in ('start','stop'):
            result=self.client.post(self.server,json.dumps({'action':action}),content_type='application/json')
            self.assertEqual(result.status_code,200)
        self.assertEqual([call.args[0] for call in command.call_args_list],['start','stop'])

    @patch('ai_gateway.runtime.change_server')
    def test_members_cannot_change_machine_server(self,service):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(self.server,{'action':'stop'}).status_code,403);service.assert_not_called()

    @patch('ai_gateway.runtime.change_server')
    def test_remote_request_and_spoofed_forwarded_header_are_denied(self,service):
        result=self.client.post(self.server,{'action':'stop'},REMOTE_ADDR='192.168.1.40',HTTP_X_FORWARDED_FOR='127.0.0.1')
        self.assertEqual(result.status_code,403);service.assert_not_called()

    @patch('ai_gateway.runtime.running_models',return_value={'running':True,'output':'NAME ID SIZE PROCESSOR UNTIL\ngemma3:1b example 600 MB 100% GPU 4 minutes'})
    def test_members_can_read_ps_on_server_computer(self,service):
        self.client.force_login(self.member)
        result=self.client.get(self.ps)
        self.assertEqual(result.status_code,200);self.assertIn('gemma3:1b',result.json()['output'])

    @patch('ai_gateway.runtime.running_models')
    def test_other_tenant_and_anonymous_cannot_inspect_runtime(self,service):
        self.client.force_login(self.other);self.assertEqual(self.client.get(self.ps).status_code,403)
        self.client.logout();self.assertEqual(self.client.get(self.ps).status_code,403);service.assert_not_called()

    def test_control_post_retains_csrf(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.owner)
        self.assertEqual(browser.post(self.server,{'action':'start'}).status_code,403)

    @patch('ai_gateway.runtime.change_server',side_effect=RuntimeErrorDetail('Started outside OrgForms'))
    def test_external_service_message_is_actionable(self,service):
        response=self.client.post(self.server,{'action':'stop'})
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['detail'],'Started outside OrgForms')


@override_settings(OLLAMA_BASE_URL='http://127.0.0.1:11434')
class RuntimeCommandTests(SimpleTestCase):
    def test_only_explicit_local_endpoints_are_controllable(self):
        for url in ('https://127.0.0.1:11434','http://example.com:11434','http://0.0.0.0:11434','http://localhost:11434/proxy','http://user:pass@localhost:11434'):
            with self.subTest(url=url),override_settings(OLLAMA_BASE_URL=url),self.assertRaises(RuntimeErrorDetail):local_endpoint()
        self.assertEqual(local_endpoint(),'http://127.0.0.1:11434')

    def test_unknown_commands_are_rejected_before_execution(self):
        with patch('ai_gateway.runtime.subprocess.Popen') as process:
            with self.assertRaises(RuntimeErrorDetail):change_server('serve; rm -rf /')
            process.assert_not_called()

    @patch('ai_gateway.runtime.shutil.which',return_value='/usr/bin/ollama')
    @patch('ai_gateway.runtime._online',return_value=False)
    @patch('ai_gateway.runtime.subprocess.run')
    def test_ps_when_off_does_not_autostart_or_execute_commands(self,process,online,binary):
        self.assertFalse(running_models()['running']);process.assert_not_called()

    @patch('ai_gateway.runtime.shutil.which',return_value='/usr/bin/ollama')
    @patch('ai_gateway.runtime._online',return_value=True)
    @patch('ai_gateway.runtime.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='NAME ID SIZE PROCESSOR UNTIL\n'))
    def test_ps_runs_fixed_command_with_configured_host_and_timeout(self,process,online,binary):
        self.assertTrue(running_models()['running'])
        args,kwargs=process.call_args;self.assertEqual(args[0],['/usr/bin/ollama','ps']);self.assertEqual(kwargs['timeout'],5)
        self.assertEqual(kwargs['env']['OLLAMA_HOST'],'http://127.0.0.1:11434');self.assertNotIn('shell',kwargs)

    @patch('ai_gateway.runtime._exclusive')
    @patch('ai_gateway.runtime._managed',return_value=None)
    @patch('ai_gateway.runtime._online',return_value=True)
    @patch('ai_gateway.runtime.os.kill')
    @patch('ai_gateway.runtime.os.killpg')
    def test_external_server_is_not_terminated(self,group,process,online,managed,lock):
        import contextlib
        lock.return_value=contextlib.nullcontext()
        with self.assertRaises(RuntimeErrorDetail):change_server('stop')
        process.assert_not_called();group.assert_not_called()

    @patch('ai_gateway.runtime._exclusive')
    @patch('ai_gateway.runtime._managed',return_value=None)
    @patch('ai_gateway.runtime._online',return_value=True)
    @patch('ai_gateway.runtime.shutil.which',return_value='/usr/bin/ollama')
    @patch('ai_gateway.runtime.subprocess.Popen')
    def test_start_when_already_running_does_not_launch_another_server(self,process,binary,online,managed,lock):
        import contextlib
        lock.return_value=contextlib.nullcontext()
        self.assertTrue(change_server('start')['running']);process.assert_not_called()

    @patch('ai_gateway.runtime.shutil.which',return_value='/usr/bin/ollama')
    @patch('ai_gateway.runtime._online',return_value=True)
    @patch('ai_gateway.runtime.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='NAME        ID           SIZE      PROCESSOR    CONTEXT    UNTIL\nqwen:0.8b   abc123       600 MB    100% GPU     8192       4 minutes from now\n'))
    def test_ps_returns_compact_running_model_metrics(self,process,online,binary):
        result=running_models()
        self.assertEqual(result['models'],[{'name':'qwen:0.8b','size':'600 MB','processor':'100% GPU','context':'8192','until':'4 minutes from now'}])
