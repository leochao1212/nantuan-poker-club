import 'dart:convert';
import 'package:flutter/foundation.dart';

const serviceOrigin = String.fromEnvironment(
  'APP_ORIGIN',
  defaultValue: 'https://poker.leoapi.dpdns.org',
);

bool isTrustedUrl(String value) {
  final uri = Uri.tryParse(value);
  final base = Uri.parse(serviceOrigin);
  if (kDebugMode &&
      base.scheme == 'http' &&
      base.host == 'localhost' &&
      uri?.scheme == 'http' &&
      uri?.host == 'localhost' &&
      uri?.port == base.port &&
      uri?.userInfo.isEmpty == true) {
    return true;
  }
  return uri != null &&
      uri.scheme == 'https' &&
      uri.host == 'poker.leoapi.dpdns.org' &&
      uri.port == 443 &&
      uri.userInfo.isEmpty;
}

Map<String, dynamic>? decodeWebState(Object value) {
  try {
    Object? decoded = value;
    for (var i = 0; i < 2 && decoded is String; i++) {
      decoded = jsonDecode(decoded);
    }
    return decoded is Map<String, dynamic> ? decoded : null;
  } on FormatException {
    return null;
  }
}
