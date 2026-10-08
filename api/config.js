// Public Supabase settings for the browser. Only the project URL and the publishable key are exposed;
// the secret key never leaves the server.
module.exports = (req, res) => {
  const url = process.env.SUPABASE_URL || '';
  const key = process.env.SUPABASE_PUBLISHABLE_KEY || '';
  res.setHeader('Cache-Control', 'public, max-age=300');
  if (!/^https:\/\/[a-z0-9]+\.supabase\.co\/?$/.test(url) || !/^sb_publishable_/.test(key)) {
    return res.status(200).json({ enabled: false, reason: !url ? 'missing_url' : !/^https:/.test(url) ? 'bad_url' : 'missing_key' });
  }
  res.status(200).json({ enabled: true, url: url.replace(/\/$/, ''), key });
};
