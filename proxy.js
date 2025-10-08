#!/usr/bin/env node

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

const GATEWAY_URL = 'https://deribit-mcp-server.onrender.com';

const server = new Server(
  {
    name: 'deribit-mcp-proxy',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  try {
    const response = await fetch(`${GATEWAY_URL}/tools`);
    const data = await response.json();
    
    return {
      tools: data.tools.map(name => ({
        name,
        description: `Deribit API tool: ${name}`,
        inputSchema: {
          type: 'object',
          properties: {},
          additionalProperties: true,
        },
      })),
    };
  } catch (error) {
    console.error('Error fetching tools:', error);
    return { tools: [] };
  }
});

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    const response = await fetch(`${GATEWAY_URL}/call`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool: request.params.name,
        params: request.params.arguments || {},
      }),
    });
    
    const data = await response.json();
    
    if (data.error) {
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${data.error}`,
          },
        ],
        isError: true,
      };
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

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('Deribit MCP Proxy running');
}

main().catch(console.error);