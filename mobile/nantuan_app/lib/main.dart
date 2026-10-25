import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'navigation_policy.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Color(0xff142b23),
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: Color(0xff142b23),
      systemNavigationBarIconBrightness: Brightness.light,
    ),
  );
  runApp(const NantuanApp());
}

class NantuanApp extends StatelessWidget {
  const NantuanApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '楠團牌室',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xff205441),
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: const Color(0xfff6ecd9),
      useMaterial3: true,
    ),
    home: const ClubScreen(),
  );
}

class ClubScreen extends StatefulWidget {
  const ClubScreen({super.key});
  @override
  State<ClubScreen> createState() => _ClubScreenState();
}

class _ClubScreenState extends State<ClubScreen> with WidgetsBindingObserver {
  static const _native = MethodChannel('org.nantuan.club/device');
  late final WebViewController _web;
  int _progress = 0;
  bool _loaded = false, _failed = false, _backPending = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _web = WebViewController(onPermissionRequest: _permission)
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xfff6ecd9))
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (value) {
            if (mounted) setState(() => _progress = value);
          },
          onPageStarted: (_) {
            if (mounted) {
              setState(() {
                _failed = false;
                _loaded = false;
              });
            }
          },
          onPageFinished: (url) {
            if (mounted) {
              setState(() {
                _loaded = !_failed && isTrustedUrl(url);
                _progress = 100;
              });
            }
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame == true && mounted) {
              setState(() => _failed = true);
            }
          },
          onNavigationRequest: (request) {
            if (isTrustedUrl(request.url)) return NavigationDecision.navigate;
            if (request.isMainFrame) _external(request.url);
            return NavigationDecision.prevent;
          },
        ),
      );
    if (_web.platform is AndroidWebViewController) {
      final android = _web.platform as AndroidWebViewController;
      unawaited(android.setMediaPlaybackRequiresUserGesture(false));
      unawaited(AndroidWebViewController.enableDebugging(kDebugMode));
    }
    unawaited(_web.loadRequest(Uri.parse(serviceOrigin)));
  }

  Future<void> _permission(WebViewPermissionRequest request) async {
    try {
      if (request.types.length != 1 ||
          !request.types.contains(WebViewPermissionResourceType.microphone) ||
          !isTrustedUrl(await _web.currentUrl() ?? '')) {
        await request.deny();
        return;
      }
      final allowed =
          await _native.invokeMethod<bool>('requestMicrophone') ?? false;
      if (allowed && isTrustedUrl(await _web.currentUrl() ?? '')) {
        await request.grant();
      } else {
        await request.deny();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('未開啟麥克風，仍可使用只聽不說。'),
              action: SnackBarAction(
                label: '開啟設定',
                onPressed: () {
                  unawaited(_native.invokeMethod<void>('openSettings'));
                },
              ),
            ),
          );
        }
      }
    } on PlatformException {
      await request.deny();
    }
  }

  Future<void> _external(String value) async {
    final uri = Uri.tryParse(value);
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty || !mounted) {
      return;
    }
    final allow = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('用瀏覽器開啟外部網站？'),
        content: Text(uri.host),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('留在 App'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('開啟瀏覽器'),
          ),
        ],
      ),
    );
    if (allow == true) {
      await _native.invokeMethod<void>('openBrowser', {'url': value});
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _loaded) {
      // Resume the existing connection and receipt. Never reload or repeat a bet.
      unawaited(
        _web.runJavaScript(
          "if(typeof resumeConnections==='function') resumeConnections('android_resume');",
        ),
      );
    }
  }

  Future<void> _back() async {
    if (_backPending) return;
    _backPending = true;
    try {
      if (_loaded && isTrustedUrl(await _web.currentUrl() ?? '')) {
        final state = decodeWebState(
          await _web.runJavaScriptReturningResult(
            "JSON.stringify({pending:(typeof busy!=='undefined'&&busy)||(typeof pendingOperation!=='undefined'&&!!pendingOperation),table:location.hash.startsWith('#table/')})",
          ),
        );
        if (state?['pending'] == true) {
          await _web.runJavaScript(
            "if(typeof notice==='function')notice('請先確認目前這筆操作，再切換頁面。');",
          );
          return;
        }
        if (state?['table'] == true) {
          await _web.runJavaScript("if(typeof route==='function'){history.replaceState(null,'','#lobby');route();}");
          return;
        }
      }
      if (await _web.canGoBack()) {
        await _web.goBack();
        return;
      }
      if (!mounted) return;
      final exit = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('離開楠團牌室？'),
          content: const Text('語音會中斷；進行中的牌局仍依原本規則結算。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('繼續使用'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('離開 App'),
            ),
          ],
        ),
      );
      if (exit == true) await SystemNavigator.pop();
    } on PlatformException {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('畫面尚未就緒，請稍後再試。')));
      }
    } finally {
      _backPending = false;
    }
  }

  Future<void> _retry() async {
    setState(() => _failed = false);
    // Recover with a fresh GET; never reload/replay a form or POST.
    await _web.loadRequest(Uri.parse(serviceOrigin));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: false,
    onPopInvokedWithResult: (didPop, result) {
      if (!didPop) unawaited(_back());
    },
    child: Scaffold(
      body: SafeArea(
        child: Stack(
          children: [
            WebViewWidget(controller: _web),
            if (_progress < 100 && !_failed)
              LinearProgressIndicator(value: _progress / 100, minHeight: 3),
            if (_failed)
              Positioned.fill(
                child: ColoredBox(
                  color: const Color(0xfff6ecd9),
                  child: Center(
                    child: Padding(
                      padding: const EdgeInsets.all(28),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(
                            Icons.wifi_off_rounded,
                            size: 56,
                            color: Color(0xff205441),
                          ),
                          const SizedBox(height: 20),
                          const Text(
                            '暫時連不上牌室',
                            style: TextStyle(
                              fontSize: 24,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 12),
                          const Text(
                            '檢查網路後再試，原本的操作不會自動重送。',
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: 24),
                          FilledButton.icon(
                            onPressed: _retry,
                            icon: const Icon(Icons.refresh),
                            label: const Text('重新連線'),
                          ),
                          TextButton(
                            onPressed: () => _native.invokeMethod<void>(
                              'openBrowser',
                              {'url': serviceOrigin},
                            ),
                            child: const Text('改用網頁版'),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    ),
  );
}
