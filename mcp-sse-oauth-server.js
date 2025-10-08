import express from 'express';
import crypto from 'crypto';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Deribit API Configuration
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// OAuth Configuration - Dynamic Client Registration (DCR) support
const registeredClients = new Map();
const authorizationCodes = new Map();
const accessTokens = new Map();
const refreshTokens = new Map();

// Well-known OAuth configuration endpoint
app.get('/.well-known/oauth-authorization-server', (req, res) => {
  const baseUrl = `https://${req.get('host')}`;
  res.json({
    issuer: baseUrl,
    authorization_endpoint: `${baseUrl}/oauth/authorize`,
    token_endpoint: `${baseUrl}/oauth/token`,
    registration_endpoint: `${baseUrl}/oauth/register`,
    response_types_supported: ['code'],
    grant_types_supported: ['authorization_code', 'refresh_token'],
    token_endpoint_auth_methods_supported: ['client_secret_post', 'client_secret_basic', 'none'],
    code_challenge_methods_supported: ['S256', 'plain'],
  });
});

// Dynamic Client Registration (DCR) endpoint
app.post('/oauth/register', (req, res) => {
  const { client_name, redirect_uris } = req.body;
  
  // Generate client credentials
  const clientId = `client_${crypto.randomBytes(16).toString('hex')}`;
  const clientSecret = crypto.randomBytes(32).toString('hex');
  
  // Store client
  registeredClients.set(clientId, {
    client_id: clientId,
    client_secret: clientSecret,
    client_name: client_name || 'Unknown Client',
    redirect_uris: redirect_uris || ['https://claude.ai/api/mcp/auth_callback'],
    created_at: Date.now(),
  });
  
  console.log(`Registered new client: ${clientId} (${client_name})`);
  
  res.json({
    client_id: clientId,
    client_secret: clientSecret,
    client_name: client_name || 'Unknown Client',
    redirect_uris: redirect_uris || ['https://claude.ai/api/mcp/auth_callback'],
  });
});

// Authorization endpoint
app.get('/oauth/authorize', (req, res) => {
  const { client_id, redirect_uri, state, response_type, code_challenge, code_challenge_method } = req.query;
  
  // Validate client
  const client = registeredClients.get(client_id);
  if (!client) {
    return res.status(400).send('Invalid client_id');
  }
  
  // For Claude, we'll auto-approve (no user interaction needed for API access)
  // Generate authorization code
  const code = crypto.randomBytes(32).toString('hex');
  
  authorizationCodes.set(code, {
    client_id,
    redirect_uri,
    code_challenge,
    code_challenge_method,
    created_at: Date.now(),
    expires_at: Date.now() + 600000, // 10 minutes
  });
  
  // Redirect back with code
  const redirectUrl = new URL(redirect_uri);
  redirectUrl.searchParams.append('code', code);
  if (state) redirectUrl.searchParams.append('state', state);
  
  console.log(`Authorization granted for client: ${client_id}`);
  res.redirect(redirectUrl.toString());
});

// Token endpoint
app.post('/oauth/token', (req, res) => {
  const { grant_type, code, refresh_token, client_id, client_secret, code_verifier } = req.body;
  
  // Validate client (allow "none" auth method for PKCE)
  if (client_secret) {
    const client = registeredClients.get(client_id);
    if (!client || client.client_secret !== client_secret) {
      return res.status(401).json({ error: 'invalid_client' });
    }
  }
  
  if (grant_type === 'authorization_code') {
    const authCode = authorizationCodes.get(code);
    
    if (!authCode) {
      return res.status(400).json({ error: 'invalid_grant' });
    }
    
    if (Date.now() > authCode.expires_at) {
      authorizationCodes.delete(code);
      return res.status(400).json({ error: 'expired_token' });
    }
    
    if (authCode.client_id !== client_id) {
      return res.status(400).json({ error: 'invalid_grant' });
    }
    
    // Validate PKCE if present
    if (authCode.code_challenge) {
      if (!code_verifier) {
        return res.status(400).json({ error: 'invalid_request', error_description: 'code_verifier required' });
      }
      
      let challenge;
      if (authCode.code_challenge_method === 'S256') {
        challenge = crypto.createHash('sha256').update(code_verifier).digest('base64url');
      } else {
        challenge = code_verifier;
      }
      
      if (challenge !== authCode.code_challenge) {
        return res.status(400).json({ error: 'invalid_grant', error_description: 'code_verifier mismatch' });
      }
    }
    
    // Generate tokens
    const accessToken = crypto.randomBytes(32).toString('hex');
    const newRefreshToken = crypto.randomBytes(32).toString('hex');
    
    accessTokens.set(accessToken, {
      client_id,
      created_at: Date.now(),
      expires_at: Date.now() + 3600000, // 1 hour
    });
    
    refreshTokens.set(newRefreshToken, {
      client_id,
      created_at: Date.now(),
    });
    
    authorizationCodes.delete(code);
    
    console.log(`Token issued for client: ${client_id}`);
    
    res.json({
      access_token: accessToken,
      token_type: 'Bearer',
      expires_in: 3600,
      refresh_token: newRefreshToken,
    });
    
  } else if (grant_type === 'refresh_token') {
    const tokenData = refreshTokens.get(refresh_token);
    
    if (!tokenData) {
      return res.status(400).json({ error: 'invalid_grant' });
    }
    
    if (tokenData.client_id !== client_id) {
      return res.status(400).json({ error: 'invalid_grant' });
    }
    
    const accessToken = crypto.randomBytes(32).toString('hex');
    
    accessTokens.set(accessToken, {
      client_id,
      created_at: Date.now(),
      expires_at: Date.now() + 3600000,
    });
    
    console.log(`Token refreshed for client: ${client_id}`);
    
    res.json({
      access_token: accessToken,
      token_type: 'Bearer',
      expires_in: 3600,
    });
    
  } else {
    res.status(400).json({ error: 'unsupported_grant_type' });
  }
});

// Middleware to validate access token
function validateToken(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'invalid_token' });
  }
  
  const token = authHeader.substring(7);
  const tokenData = accessTokens.get(token);
  
  if (!tokenData) {
    return res.status(401).json({ error: 'invalid_token' });
  }
  
  if (Date.now() > tokenData.expires_at) {
    accessTokens.delete(token);
    return res.status(401).json({ error: 'expired_token' });
  }
  
  req.client_id = tokenData.client_id;
  next();
}

// Create MCP Server
function createMCPServer() {
  const mcpServer = new Server(
    {
      name: 'deribit-mcp-server',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  const tools = [
    {
      name: 'get_ticker',
      description: 'Get ticker data for a specific instrument including price, volume, and funding rate',
      inputSchema: {
        type: 'object',
        properties: {
          instrument_name: {
            type: 'string',
            description: 'Instrument name (e.g., BTC-PERPETUAL, ETH-PERPETUAL)',
          },
        },
        required: ['instrument_name'],
      },
    },
    {
      name: 'get_instruments',
      description: 'Get all available trading instruments on Deribit',
      inputSchema: {
        type: 'object',
        properties: {
          currency: {
            type: 'string',
            description: 'Currency symbol (BTC, ETH, USDC, USDT, EURR)',
          },
          kind: {
            type: 'string',
            description: 'Instrument kind (future, option, spot)',
          },
        },
      },
    },
    {
      name: 'get_orderbook',
      description: 'Get order book data for an instrument',
      inputSchema: {
        type: 'object',
        properties: {
          instrument_name: {
            type: 'string',
            description: 'Instrument name',
          },
          depth: {
            type: 'number',
            description: 'Order book depth',
          },
        },
        required: ['instrument_name'],
      },
    },
  ];

  mcpServer.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools };
  });

  mcpServer.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

    try {
      let endpoint = '';
      const params = args || {};

      switch (name) {
        case 'get_ticker':
          endpoint = '/public/ticker';
          break;
        case 'get_instruments':
          endpoint = '/public/get_instruments';
          break;
        case 'get_orderbook':
          endpoint = '/public/get_order_book';
          break;
        default:
          throw new Error(`Unknown tool: ${name}`);
      }

      const url = new URL(`${DERIBIT_API_BASE}${endpoint}`);
      Object.keys(params).forEach(key => {
        if (params[key] !== undefined && params[key] !== null) {
          url.searchParams.append(key, String(params[key]));
        }
      });

      const response = await fetch(url.toString());
      const data = await response.json();

      if (data.error) {
        throw new Error(data.error.message);
      }

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(data.result, null, 2),
          },
        ],
      };
    } catch (error) {
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${error.message}`,
          },
        ],
        isError: true,
      };
    }
  });

  return mcpServer;
}

// SSE endpoint (protected by OAuth)
app.get('/sse', validateToken, async (req, res) => {
  console.log(`New SSE connection from client: ${req.client_id}`);
  
  const mcpServer = createMCPServer();
  const transport = new SSEServerTransport('/message', res);
  
  await mcpServer.connect(transport);
  
  req.on('close', () => {
    console.log('SSE connection closed');
  });
});

// Message endpoint for SSE (protected by OAuth)
app.post('/message', validateToken, async (req, res) => {
  res.status(200).end();
});

// Health check
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server with OAuth',
    version: '1.0.0',
    mcp_endpoint: '/sse',
    oauth_discovery: '/.well-known/oauth-authorization-server',
    supports_dcr: true,
  });
});

app.listen(PORT, () => {
  console.log(`Deribit MCP Server (SSE + OAuth) running on port ${PORT}`);
  console.log(`OAuth discovery: http://localhost:${PORT}/.well-known/oauth-authorization-server`);
  console.log(`MCP SSE endpoint: http://localhost:${PORT}/sse`);
});