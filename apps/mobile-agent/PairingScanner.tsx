import React, { useRef, useState } from 'react';
import { AppState, Linking, Modal, Pressable, Text, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { PairingTicket, parsePairingTicket } from './lib/pairing';

export default function PairingScanner({ onScanned, disabled }: { onScanned: (ticket: PairingTicket) => void; disabled: boolean }) {
  const [permission, requestPermission] = useCameraPermissions();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [active, setActive] = useState(AppState.currentState === 'active');
  const scanned = useRef(false);
  React.useEffect(() => { const sub = AppState.addEventListener('change', s => setActive(s === 'active')); return () => sub.remove(); }, []);
  const control = (title: string, fn: () => void) => <Pressable style={{ padding: 14, backgroundColor: '#cf010e', borderRadius: 9, alignItems: 'center' }} onPress={fn}><Text style={{ color: 'white', fontWeight: '600', fontSize: 16 }}>{title}</Text></Pressable>;
  return <>
    <Pressable disabled={disabled} style={{ padding: 14, backgroundColor: '#cf010e', borderRadius: 9, alignItems: 'center', opacity: disabled ? .5 : 1 }} onPress={() => { scanned.current = false; setError(''); setOpen(true); }}><Text style={{ color: 'white', fontSize: 16, fontWeight: '600' }}>扫码配对</Text></Pressable>
    <Modal visible={open} onRequestClose={() => setOpen(false)} animationType="slide">
      <View style={{ flex: 1, backgroundColor: '#f7f4f1', padding: 24, paddingTop: 50, gap: 16 }}>
        <Text style={{ fontSize: 22, fontWeight: '700' }}>扫描 Beacon 配对二维码</Text>
        <Text>将网页“设置 → 手机执行”中的二维码放入取景框。</Text>
        {permission?.granted ? <View style={{ height: 320, borderRadius: 12, overflow: 'hidden' }}>{open && active && <CameraView style={{ flex: 1 }} facing="back" barcodeScannerSettings={{ barcodeTypes: ['qr'] }} onBarcodeScanned={({ data }) => {
          if (scanned.current) return;
          scanned.current = true;
          try { const ticket = parsePairingTicket(data); setOpen(false); onScanned(ticket); }
          catch (e) { setError(e instanceof Error ? e.message : String(e)); }
        }} />}</View> : <><Text>仅扫描配对码时使用相机，不拍照、不录音、不上传画面。也可以返回手动配对。</Text>{control(permission?.canAskAgain === false ? '打开相机权限设置' : '允许使用相机', () => { if (permission?.canAskAgain === false) void Linking.openSettings(); else void requestPermission(); })}</>}
        {!!error && <><Text accessibilityRole="alert" style={{ color: '#cf010e' }}>{error}</Text><Pressable accessibilityRole="button" style={{ padding: 14, backgroundColor: '#cf010e', borderRadius: 9, alignItems: 'center' }} onPress={() => { scanned.current = false; setError(''); }}><Text style={{color:'white'}}>重新扫描</Text></Pressable></>}
        {control('返回', () => setOpen(false))}
      </View>
    </Modal>
  </>;
}
