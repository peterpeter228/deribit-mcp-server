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

// Enable CORS for all routes
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

// Deribit API Configuration
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';

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

// Public SSE endpoint - CORRECT MCP SSE Implementation
app.get('/sse-public', async (req, res) => {
  console.log('New public SSE connection - MCP protocol');
  
  // Set SSE headers
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Access-Control-Allow-Origin': '*',
  });

  // CRITICAL: Send endpoint event first (required by MCP SSE spec)
  const sessionId = crypto.randomBytes(16).toString('hex');
  const messageEndpoint = `/message-public?sessionId=${sessionId}`;
  
  res.write(`event: endpoint\n`);
  res.write(`data: ${messageEndpoint}\n\n`);
  console.log(`Sent endpoint event: ${messageEndpoint}`);
  
  // Create MCP server for this session
  const mcpServer = createMCPServer();
  const transport = new SSEServerTransport(messageEndpoint, res);
  
  await mcpServer.connect(transport);
  
  req.on('close', () => {
    console.log('Public SSE connection closed');
  });
});

// Public message endpoint
app.post('/message-public', async (req, res) => {
  console.log('Received message on /message-public:', req.body);
  res.status(200).end();
});

// Health check
app.get('/', (req, res) => {
  res.json({
    status: 'ok',
    name: 'Deribit MCP Server',
    version: '1.0.0',
    mcp_endpoint: '/sse-public',
    transport: 'sse',
  });
});

app.listen(PORT, () => {
  console.log(`Deribit MCP Server running on port ${PORT}`);
  console.log(`MCP SSE endpoint: http://localhost:${PORT}/sse-public`);
});