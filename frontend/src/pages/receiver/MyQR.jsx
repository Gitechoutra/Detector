import { QRCodeCanvas } from 'qrcode.react';
import { useRef } from 'react';
import { useToast } from '../../components/Toast';
import { ErrorNote, Loading, PageHead } from '../../components/ui';
import { useApi } from '../../hooks';

export default function MyQR() {
  const toast = useToast();
  const { data, error } = useApi('/receiver/dashboard');
  const wrap = useRef(null);
  if (!data) return error ? <ErrorNote error={error} /> : <Loading />;
  const { account } = data;

  const download = () => {
    const canvas = wrap.current?.querySelector('canvas');
    if (!canvas) return;
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = `${account.upi_id}-qr.png`;
    a.click();
  };

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied to clipboard.', 'success');
    } catch {
      toast('Copy failed – select the text instead.', 'warning');
    }
  };

  return (
    <>
      <PageHead title="My QR & payment details" subtitle="Share any of these with a sender. All three methods reach the same account." />
      <div className="grid grid-2">
        <div className="card card-pad" style={{ textAlign: 'center' }}>
          <div className="qr-box" ref={wrap}>
            <QRCodeCanvas value={account.qr_payload} size={220} level="M" includeMargin />
          </div>
          <h2 className="mt-16">{account.holder_name}</h2>
          <p className="muted">{account.upi_id}</p>
          <div className="row mt-16" style={{ justifyContent: 'center' }}>
            <button className="btn btn-primary" onClick={download}>⬇ Download QR</button>
            <button className="btn btn-ghost" onClick={() => copy(account.qr_payload)}>Copy QR data</button>
          </div>
          <p className="muted small mt-16">Simulated UPI QR. The sender uploads this image in Send Money → QR Code.</p>
        </div>
        <div className="card card-pad">
          <h2>Bank details</h2>
          <dl className="kv mt-16">
            <dt>Account holder</dt><dd>{account.holder_name}</dd>
            <dt>UPI ID</dt><dd className="mono">{account.upi_id} <button className="link-btn small" onClick={() => copy(account.upi_id)}>copy</button></dd>
            <dt>Account number</dt><dd className="mono">{account.account_number} <button className="link-btn small" onClick={() => copy(account.account_number)}>copy</button></dd>
            <dt>IFSC</dt><dd className="mono">{account.ifsc}</dd>
            <dt>Account type</dt><dd>{account.account_type}</dd>
            <dt>Status</dt><dd>{account.status}</dd>
          </dl>
          <div className="notice notice-info mt-16">ℹ Payments to you are credited only when the sender’s payment is approved by the fraud detection system.</div>
        </div>
      </div>
    </>
  );
}
