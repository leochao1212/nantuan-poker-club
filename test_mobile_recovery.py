"""Recovery phase telemetry is paired, bounded and independent of game writes."""
import json,unittest
from unittest.mock import patch
import server
import test_connection_review as streams
from test_app import Client

class RecoveryTelemetry(unittest.TestCase):
    setUp=streams.ReadOnlyStreams.setUp
    close=streams.ReadOnlyStreams.close

    def event(self,kind='stream_error',**fields):
        return {'kind':kind,'client':'recovery_browser_page_001','attempt_id':'recovery_attempt_00000001',
                'room_id':self.rid,'visibility':'visible','online':True,'reason':'visible',**fields}

    def test_fast_recovery_and_other_pages_keep_both_phase_records(self):
        with patch.object(server,'CLIENT_EVENT_AT',{}),patch.object(server,'CLIENT_EVENT_BUDGET',{}),patch('builtins.print') as output:
            c=self.clients[0]
            for kind in ('recovery_started','stream_error','recovery_synced','stream_recovered'):
                status,body=c.call('/api/online/client-event',self.event(kind,duration_ms=27,delivery='snapshot',password='NEVER_LOG_THIS',hole=['As','Ah']))
                self.assertEqual(status,200,body)
            status,duplicate=c.call('/api/online/client-event',self.event('stream_recovered'))
            self.assertEqual(status,200);self.assertTrue(duplicate['duplicate'])
            self.assertEqual(c.call('/api/online/client-event',self.event(client='recovery_browser_page_002'))[0],200)
            self.assertEqual(c.call('/api/online/client-event',self.event(attempt_id='recovery_attempt_00000002'))[0],200)
            logs=[]
            for call in output.call_args_list:
                try:r=json.loads(call.args[0])
                except (ValueError,TypeError,IndexError):continue
                if r.get('event')=='client_connection':logs.append(r)
            self.assertEqual(len(logs),6)
            self.assertEqual([r['kind'] for r in logs[:4]],['recovery_started','stream_error','recovery_synced','stream_recovered'])
            self.assertEqual(logs[3]['duration_ms'],27)
            self.assertNotIn('NEVER_LOG_THIS',json.dumps(logs));self.assertNotIn('hole',json.dumps(logs))

    def test_telemetry_budget_does_not_block_game_or_other_accounts(self):
        with patch.object(server,'CLIENT_EVENT_AT',{}),patch.object(server,'CLIENT_EVENT_BUDGET',{}):
            c=self.clients[0]
            for i in range(120):
                status,body=c.call('/api/online/client-event',self.event(attempt_id=f'recovery_attempt_{i:08d}'))
                self.assertEqual(status,200,body)
            self.assertEqual(c.call('/api/online/client-event',self.event(attempt_id='recovery_attempt_over_limit'))[0],429)
            self.assertEqual(self.clients[1].call('/api/online/client-event',self.event())[0],200)
            r=c.call(self.path)[1]
            self.assertEqual(c.call(self.path+'/start',{'revision':r['revision'],'operation_id':'game_after_telemetry_limit'})[0],200)
            self.assertEqual(c.call('/api/online/presence',{'room_id':self.rid})[0],200)

    def test_telemetry_auth_validation_and_csrf(self):
        self.assertEqual(Client(self.clients[0].base).call('/api/online/client-event',self.event())[0],401)
        for change in ({'kind':'secret'},{'attempt_id':'bad'},{'reason':'arbitrary private message'},{'delivery':'unknown'},{'visibility':'other'}):
            self.assertEqual(self.clients[0].call('/api/online/client-event',self.event(**change))[0],400)
        self.assertEqual(self.clients[0].call('/api/online/client-event',self.event(),origin='https://untrusted.invalid')[0],403)

if __name__=='__main__':unittest.main()
