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

// Enable CORS
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, Mcp-Session-Id');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

// Deribit API Configuration
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

// Session storage
const sessions = new Map();

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

// Streamable HTTP MCP endpoint (modern standard)
app.all('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'] || crypto.randomBytes(16).toString('hex');
  
  // Handle POST - Client sending requests
  if (req.method === 'POST') {
    console.log(`MCP POST request - Session: ${sessionId}`);
    
    const isInitialize = req.body?.method === 'initialize';
    
    // Get or create session
    let session = sessions.get(sessionId);
    if (!session || isInitialize) {
      const mcpServer = createMCPServer();
      session = { mcpServer, responses: [] };
      sessions.set(sessionId, session);
      console.log(`Created new session: ${sessionId}`);
    }
    
    // Set headers
    res.writeHead(200, {
      'Content-Type': 'application/json',
      'Mcp-Session-Id': sessionId,
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Expose-Headers': 'Mcp-Session-Id',
    });
    
    // Process the request
    try {
      const response = await session.mcpServer.handleRequest(req.body);
      res.end(JSON.stringify(response));
    } catch (error) {
      console.error('Error handling request:', error);
      res.end(JSON.stringify({
        jsonrpc: '2.0',
        id: req.body?.id,
        error: {
          code: -32603,
          message: error.message,
        },
      }));
    }
    return;
  }
  
  // Handle GET - Optional SSE stream for notifications
  if (req.method === 'GET') {
    console.log(`MCP GET request (SSE) - Session: ${sessionId}`);
    
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*',
    });
    
    // Keep connection alive
    const keepAliveInterval = setInterval(() => {
      res.write(':keepalive\n\n');
    }, 30000);
    
    req.on('close', () => {
      clearInterval(keepAliveInterval);
      console.log(`SSE connection closed for session: ${sessionId}`);
    });
    
    return;
  }
  
  res.status(405).json({ error: 'Method not allowed' });
});

// Health check
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '1.0.0',
    mcp_endpoint: '/mcp',
    transport: 'streamable-http',
    supports_sse_notifications: true,
  });
});

app.listen(PORT, () => {
  console.log(`Deribit MCP Server (Streamable HTTP) running on port ${PORT}`);
  console.log(`MCP endpoint: http://localhost:${PORT}/mcp`);
});