import { Empty, ErrorNote, Loading, PageHead, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime } from '../../utils/format';

export default function UserSecurity() {
  const { data, error } = useApi('/user/security', null, { interval: 10000 });
  if (!data) return error ? <ErrorNote error={error} /> : <Loading />;
  return (
    <>
      <PageHead title="Security" subtitle="Devices, logins and security events on your account." />
      <div className="grid grid-2">
        <div className="card">
          <div className="card-head"><h2>Devices</h2></div>
          {data.devices.length === 0 ? <Empty title="No devices yet" /> : (
            <div className="list">
              {data.devices.map((d) => (
                <div className="list-item" key={d.id}>
                  <div style={{ fontSize: 22 }}>💻</div>
                  <div style={{ flex: 1 }}>
                    <strong>{d.device_name}</strong>{d.id === data.current_device_id && <span className="badge b-blue" style={{ marginLeft: 6 }}>This device</span>}
                    <div className="muted small">First seen {dateTime(d.first_seen_at)} · last {dateTime(d.last_seen_at)} · {d.last_ip}</div>
                  </div>
                  {d.is_trusted ? <span className="badge b-green">Trusted</span> : <span className="badge b-amber">New / unverified</span>}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h2>Security events</h2></div>
          {data.events.length === 0 ? <Empty title="No events" /> : (
            <div className="list">
              {data.events.map((e) => (
                <div className="list-item" key={e.id}>
                  <StatusBadge status={e.severity} />
                  <div style={{ flex: 1 }}>
                    <strong className="small">{e.event_type.replaceAll('_', ' ')}</strong>
                    <div className="muted small">{e.description}</div>
                  </div>
                  <span className="muted small nowrap">{dateTime(e.created_at)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="card mt-16">
        <div className="card-head"><h2>Login history</h2></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>When</th><th>Result</th><th>City</th><th>IP</th><th>Device</th></tr></thead>
            <tbody>
              {data.logins.map((l, i) => (
                <tr key={i}>
                  <td className="nowrap">{dateTime(l.created_at)}</td>
                  <td>{l.success ? <span className="badge b-green">Success</span> : <span className="badge b-red">Failed · {l.failure_reason?.replaceAll('_', ' ').toLowerCase()}</span>}</td>
                  <td>{l.city || '—'}</td><td className="mono">{l.ip_address}</td>
                  <td>{l.is_new_device ? <span className="badge b-amber">New device</span> : <span className="muted small">Known</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
