import express from 'express';
import session from 'express-session';
import jwt from 'jsonwebtoken';
import bcrypt from 'bcryptjs';
import fetch from 'node-fetch';
import crypto from 'crypto';

const app = express();
const PORT = process.env.PORT || 3000;

// Secret keys (in production, use environment variables)
const JWT_SECRET = process.env.JWT_SECRET || crypto.randomBytes(32).toString('hex');
const SESSION_SECRET = process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex');

// Store for authorization codes and tokens (in production, use a database)
const authCodes = new Map();
const refreshTokens = new Map();
const users = new Map(); // Simple user store

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(session({
  secret: SESSION_SECRET,
  resave: false,
  saveUninitialized: false,
  cookie: { secure: process.env.NODE_ENV === 'production' }
}));

// Deribit API proxy
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// OAuth endpoints
app.get('/oauth/authorize', (req, res) => {
  const { client_id, redirect_uri, response_type, state } = req.query;
  
  // Simple authorization page
  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Authorize Deribit MCP Server</title>
      <style>
        body {
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          max-width: 400px;
          margin: 100px auto;
          padding: 20px;
        }
        .container {
          background: white;
          padding: 30px;
          border-radius: 8px;
          box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h2 { margin-top: 0; }
        input {
          width: 100%;
          padding: 10px;
          margin: 10px 0;
          border: 1px solid #ddd;
          border-radius: 4px;
          box-sizing: border-box;
        }
        button {
          width: 100%;
          padding: 12px;
          background: #5436DA;
          color: white;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 16px;
        }
        button:hover { background: #4229B8; }
        .info { color: #666; font-size: 14px; margin: 15px 0; }
      </style>
    </head>
    <body>
      <div class="container">
        <h2>Authorize Deribit MCP Server</h2>
        <p class="info">Enter any email to authorize access to Deribit market data</p>
        <form action="/oauth/authorize" method="post">
          <input type="email" name="email" placeholder="Email" required />
          <input type="hidden" name="client_id" value="${client_id}" />
          <input type="hidden" name="redirect_uri" value="${redirect_uri}" />
          <input type="hidden" name="response_type" value="${response_type}" />
          <input type="hidden" name="state" value="${state}" />
          <button type="submit">Authorize</button>
        </form>
      </div>
    </body>
    </html>
  `);
});

app.post('/oauth/authorize', (req, res) => {
  const { email, client_id, redirect_uri, response_type, state } = req.body;
  
  // Generate authorization code
  const code = crypto.randomBytes(32).toString('hex');
  
  // Store authorization code
  authCodes.set(code, {
    email,
    client_id,
    redirect_uri,
    expiresAt: Date.now() + 600000 // 10 minutes
  });
  
  // Store user
  if (!users.has(email)) {
    users.set(email, { email, createdAt: Date.now() });
  }
  
  // Redirect back to Claude with authorization code
  const redirectUrl = new URL(redirect_uri);
  redirectUrl.searchParams.append('code', code);
  if (state) redirectUrl.searchParams.append('state', state);
  
  res.redirect(redirectUrl.toString());
});

app.post('/oauth/token', async (req, res) => {
  const { grant_type, code, refresh_token, client_id, redirect_uri } = req.body;
  
  if (grant_type === 'authorization_code') {
    // Exchange authorization code for tokens
    const authData = authCodes.get(code);
    
    if (!authData) {
      return res.status(400).json({ error: 'invalid_grant' });
    }
    
    if (Date.now() > authData.expiresAt) {
      authCodes.delete(code);
      return res.status(400).json({ error: 'expired_token' });
    }
    
    // Generate tokens
    const accessToken = jwt.sign(
      { email: authData.email, client_id },
      JWT_SECRET,
      { expiresIn: '1h' }
    );
    
    const newRefreshToken = crypto.randomBytes(32).toString('hex');
    refreshTokens.set(newRefreshToken, {
      email: authData.email,
      client_id,
      createdAt: Date.now()
    });
    
    // Clean up authorization code
    authCodes.delete(code);
    
    res.json({
      access_token: accessToken,
      token_type: 'Bearer',
      expires_in: 3600,
      refresh_token: newRefreshToken
    });
    
  } else if (grant_type === 'refresh_token') {
    // Refresh access token
    const tokenData = refreshTokens.get(refresh_token);
    
    if (!tokenData) {
      return res.status(400).json({ error: 'invalid_grant' });
    }
    
    const accessToken = jwt.sign(
      { email: tokenData.email, client_id },
      JWT_SECRET,
      { expiresIn: '1h' }
    );
    
    res.json({
      access_token: accessToken,
      token_type: 'Bearer',
      expires_in: 3600
    });
    
  } else {
    res.status(400).json({ error: 'unsupported_grant_type' });
  }
});

// Middleware to verify JWT token
function authenticateToken(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1];
  
  if (!token) {
    return res.status(401).json({ error: 'No token provided' });
  }
  
  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) {
      return res.status(403).json({ error: 'Invalid token' });
    }
    req.user = user;
    next();
  });
}

// Health check endpoint (public)
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    service: 'Deribit MCP Server',
    version: '1.0.0',
    oauth: {
      authorization_endpoint: '/oauth/authorize',
      token_endpoint: '/oauth/token'
    },
    endpoints: {
      tools: '/api/tools',
      call: '/api/call'
    }
  });
});

// OAuth configuration/discovery endpoint
app.get('/.well-known/oauth-authorization-server', (req, res) => {
  const baseUrl = `https://${req.get('host')}`;
  res.json({
    issuer: baseUrl,
    authorization_endpoint: `${baseUrl}/oauth/authorize`,
    token_endpoint: `${baseUrl}/oauth/token`,
    response_types_supported: ['code'],
    grant_types_supported: ['authorization_code', 'refresh_token'],
    token_endpoint_auth_methods_supported: ['client_secret_post', 'client_secret_basic']
  });
});

// Get available tools (requires authentication)
app.get('/api/tools', authenticateToken, (req, res) => {
  const tools = [
    'get_instruments',
    'get_ticker',
    'get_tickers',
    'get_orderbook',
    'get_tradingview_chart',
    'get_last_trades',
    'get_funding_rate_history',
    'get_funding_rate_value',
    'get_index_price',
    'get_volatility_index',
    'get_historical_volatility',
    'get_book_summary_by_currency',
    'get_book_summary_by_instrument',
    'get_delivery_prices',
    'ticker_statistics'
  ];
  
  res.json({ tools });
});

// Call a tool (requires authentication)
app.post('/api/call', authenticateToken, async (req, res) => {
  const { tool, params } = req.body;
  
  if (!tool) {
    return res.status(400).json({ error: 'Tool name is required' });
  }

  try {
    let endpoint = '';
    let queryParams = params || {};
    
    // Map tool names to Deribit API endpoints
    switch (tool) {
      case 'get_instruments':
        endpoint = '/public/get_instruments';
        break;
      case 'get_ticker':
        endpoint = '/public/ticker';
        break;
      case 'get_tickers':
        endpoint = '/public/get_book_summary_by_currency';
        break;
      case 'get_orderbook':
        endpoint = '/public/get_order_book';
        break;
      case 'get_tradingview_chart':
        endpoint = '/public/get_tradingview_chart_data';
        break;
      case 'get_last_trades':
        endpoint = '/public/get_last_trades_by_instrument';
        break;
      case 'get_funding_rate_history':
        endpoint = '/public/get_funding_rate_history';
        break;
      case 'get_funding_rate_value':
        endpoint = '/public/get_funding_rate_value';
        break;
      case 'get_index_price':
        endpoint = '/public/get_index_price';
        break;
      case 'get_volatility_index':
        endpoint = '/public/get_volatility_index_data';
        break;
      case 'get_historical_volatility':
        endpoint = '/public/get_historical_volatility';
        break;
      case 'get_book_summary_by_currency':
        endpoint = '/public/get_book_summary_by_currency';
        break;
      case 'get_book_summary_by_instrument':
        endpoint = '/public/get_book_summary_by_instrument';
        break;
      case 'get_delivery_prices':
        endpoint = '/public/get_delivery_prices';
        break;
      case 'ticker_statistics':
        endpoint = '/public/ticker';
        break;
      default:
        return res.status(400).json({ error: `Unknown tool: ${tool}` });
    }
    
    // Build URL with query parameters
    const url = new URL(`${DERIBIT_API_BASE}${endpoint}`);
    Object.keys(queryParams).forEach(key => {
      if (queryParams[key] !== undefined && queryParams[key] !== null) {
        url.searchParams.append(key, String(queryParams[key]));
      }
    });
    
    // Make request to Deribit
    const response = await fetch(url.toString());
    const data = await response.json();
    
    if (data.error) {
      return res.status(400).json({ error: data.error.message });
    }
    
    res.json({ result: data.result });
    
  } catch (error) {
    console.error('Error calling tool:', error);
    res.status(500).json({ error: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`Deribit MCP OAuth Server running on port ${PORT}`);
});