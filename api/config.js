// Public Supabase settings for the browser. Only the project URL and the publishable (or legacy anon) key are exposed;
// the secret key never leaves the server.
module.exports = (req, res) => {
  const clean = v => String(v || '').trim().replace(/^["']|["']$/g, '').trim();
  let url = clean(process.env.SUPABASE_URL);
  const key = clean(process.env.SUPABASE_PUBLISHABLE_KEY || process.env.SUPABASE_ANON_KEY);
  res.setHeader('Cache-Control', 'no-store');
  if (/^[a-z0-9]{20}$/.test(url)) url = 'https://' + url + '.supabase.co';           // project ref only
  url = url.replace(/\/(rest|auth)\/v1.*$/, '').replace(/\/+$/, '');
  const urlOk = /^https:\/\/[a-z0-9]+\.supabase\.co$/.test(url);
  const keyOk = /^sb_publishable_[A-Za-z0-9_\-]+$/.test(key) || /^eyJ[\w-]+\.[\w-]+\.[\w-]+$/.test(key);
  const wrongKey = /^sb_secret_/.test(key);
  if (!urlOk || !keyOk) {
    return res.status(200).json({ enabled: false,
      reason: !url ? 'SUPABASE_URL is missing' : !urlOk ? 'SUPABASE_URL is not a https://….supabase.co address (starts: ' + url.slice(0, 10) + '…)'
        : !key ? 'SUPABASE_PUBLISHABLE_KEY is missing' : wrongKey ? 'SUPABASE_PUBLISHABLE_KEY holds the secret key; use the sb_publishable_ key'
        : 'SUPABASE_PUBLISHABLE_KEY doesn’t look like a publishable key (starts: ' + key.slice(0, 6) + '…)' });
  }
  res.status(200).json({ enabled: true, url, key });
};
