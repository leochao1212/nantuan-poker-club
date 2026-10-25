import 'package:flutter_test/flutter_test.dart';
import 'package:nantuan_club/navigation_policy.dart';
void main() {
  test('Only the exact HTTPS service origin stays inside the WebView', () {
    expect(isTrustedUrl('$serviceOrigin/#table/123'), isTrue);
    for (final url in ['http://poker.leoapi.dpdns.org/', 'https://poker.leoapi.dpdns.org.attacker.test/', 'https://poker.leoapi.dpdns.org:444/', 'https://user@poker.leoapi.dpdns.org/', 'file:///etc/passwd', 'javascript:alert(1)', 'https://example.org/']) {
      expect(isTrustedUrl(url), isFalse, reason: url);
    }
  });
  test('Receipt state survives Android JS return-value encoding', () {
    expect(decodeWebState('{"pending":true,"table":true}')?['pending'], isTrue);
    expect(decodeWebState('"{\\"pending\\":false}"')?['pending'], isFalse);
    expect(decodeWebState('not json'), isNull);
  });
}
