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

// Session storage for connected clients
const sessions = new Map();

// Create MCP Server instance
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

// Streamable HTTP MCP endpoint
app.post('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'] || crypto.randomBytes(16).toString('hex');
  
  console.log(`MCP POST request - Session: ${sessionId}`);
  console.log('Request body:', JSON.stringify(req.body, null, 2));
  
  try {
    const isInitialize = req.body?.method === 'initialize';
    
    // Get or create session
    let session = sessions.get(sessionId);
    if (!session || isInitialize) {
      const mcpServer = createMCPServer();
      
      // Create a simple transport that doesn't need SSE
      const mockTransport = {
        start: async () => {},
        close: async () => {},
        send: async (message) => {
          console.log('Server sending:', JSON.stringify(message, null, 2));
        },
      };
      
      await mcpServer.connect(mockTransport);
      
      session = { mcpServer, connected: true };
      sessions.set(sessionId, session);
      console.log(`Created new session: ${sessionId}`);
    }
    
    // Process the JSON-RPC request directly
    const request = req.body;
    let response;
    
    if (request.method === 'initialize') {
      response = {
        jsonrpc: '2.0',
        id: request.id,
        result: {
          protocolVersion: '2024-11-05',
          capabilities: {
            tools: {},
          },
          serverInfo: {
            name: 'deribit-mcp-server',
            version: '1.0.0',
          },
        },
      };
    } else if (request.method === 'tools/list') {
      const result = await session.mcpServer._requestHandlers.get('tools/list')();
      response = {
        jsonrpc: '2.0',
        id: request.id,
        result,
      };
    } else if (request.method === 'tools/call') {
      const result = await session.mcpServer._requestHandlers.get('tools/call')(request);
      response = {
        jsonrpc: '2.0',
        id: request.id,
        result,
      };
    } else {
      response = {
        jsonrpc: '2.0',
        id: request.id,
        error: {
          code: -32601,
          message: `Method not found: ${request.method}`,
        },
      };
    }
    
    console.log('Response:', JSON.stringify(response, null, 2));
    
    res.writeHead(200, {
      'Content-Type': 'application/json',
      'Mcp-Session-Id': sessionId,
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Expose-Headers': 'Mcp-Session-Id',
    });
    
    res.end(JSON.stringify(response));
    
  } catch (error) {
    console.error('Error handling request:', error);
    res.status(500).json({
      jsonrpc: '2.0',
      id: req.body?.id,
      error: {
        code: -32603,
        message: error.message,
      },
    });
  }
});

// Health check
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '1.0.0',
    mcp_endpoint: '/mcp',
    transport: 'streamable-http',
  });
});

app.listen(PORT, () => {
  console.log(`Deribit MCP Server (Streamable HTTP) running on port ${PORT}`);
  console.log(`MCP endpoint: http://localhost:${PORT}/mcp`);
});