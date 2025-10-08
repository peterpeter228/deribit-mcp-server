#!/usr/bin/env node

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

// Deribit API Configuration
const DERIBIT_API_BASE = 'https://www.deribit.com/api/v2';
const DERIBIT_TEST_API_BASE = 'https://test.deribit.com/api/v2';

interface DeribitConfig {
  apiKey?: string;
  apiSecret?: string;
  testnet?: boolean;
}

class DeribitMCPServer {
  private server: Server;
  private config: DeribitConfig;
  private accessToken?: string;
  private refreshToken?: string;

  constructor(config: DeribitConfig = {}) {
    this.config = config;
    this.server = new Server(
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

    this.setupHandlers();
  }

  private getBaseUrl(): string {
    return this.config.testnet ? DERIBIT_TEST_API_BASE : DERIBIT_API_BASE;
  }

  private async authenticate(): Promise<void> {
    if (!this.config.apiKey || !this.config.apiSecret) {
      return; // Public endpoints only
    }

    try {
      const response = await fetch(`${this.getBaseUrl()}/public/auth`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          grant_type: 'client_credentials',
          client_id: this.config.apiKey,
          client_secret: this.config.apiSecret,
        }),
      });

      const data: any = await response.json();
      if (data.result) {
        this.accessToken = data.result.access_token;
        this.refreshToken = data.result.refresh_token;
      }
    } catch (error) {
      console.error('Authentication failed:', error);
    }
  }

  private async makeRequest(endpoint: string, params: Record<string, any> = {}): Promise<any> {
    const url = new URL(`${this.getBaseUrl()}${endpoint}`);
    Object.keys(params).forEach(key => {
      if (params[key] !== undefined && params[key] !== null) {
        url.searchParams.append(key, String(params[key]));
      }
    });

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    const response = await fetch(url.toString(), { headers });
    const data: any = await response.json();

    if (data.error) {
      throw new Error(`Deribit API Error: ${data.error.message}`);
    }

    return data.result;
  }

  private setupHandlers(): void {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: this.getTools(),
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) =>
      this.handleToolCall(request.params.name, request.params.arguments || {})
    );
  }

  private getTools(): Tool[] {
    return [
      {
        name: 'get_instruments',
        description: 'Get all available trading instruments. Use to discover available markets, futures, options, and perpetuals on Deribit.',
        inputSchema: {
          type: 'object',
          properties: {
            currency: {
              type: 'string',
              description: 'Currency symbol (BTC, ETH, USDC, USDT, EURR)',
              enum: ['BTC', 'ETH', 'USDC', 'USDT', 'EURR', 'any'],
            },
            kind: {
              type: 'string',
              description: 'Instrument kind',
              enum: ['future', 'option', 'spot', 'future_combo', 'option_combo'],
            },
            expired: {
              type: 'boolean',
              description: 'Include expired instruments',
              default: false,
            },
          },
        },
      },
      {
        name: 'get_ticker',
        description: 'Get ticker data for a specific instrument including price, volume, and funding rate.',
        inputSchema: {
          type: 'object',
          properties: {
            instrument_name: {
              type: 'string',
              description: 'Instrument name (e.g., BTC-PERPETUAL, ETH-29MAR24-3000-C)',
            },
          },
          required: ['instrument_name'],
        },
      },
      {
        name: 'get_tickers',
        description: 'Get ticker data for multiple instruments. More efficient than multiple get_ticker calls.',
        inputSchema: {
          type: 'object',
          properties: {
            currency: {
              type: 'string',
              description: 'Currency symbol (BTC, ETH, USDC, USDT, EURR)',
              enum: ['BTC', 'ETH', 'USDC', 'USDT', 'EURR'],
            },
            kind: {
              type: 'string',
              description: 'Instrument kind',
              enum: ['future', 'option', 'spot', 'future_combo', 'option_combo'],
            },
          },
          required: ['currency'],
        },
      },
      {
        name: 'get_orderbook',
        description: 'Get order book data for an instrument including bids, asks, and depth.',
        inputSchema: {
          type: 'object',
          properties: {
            instrument_name: {
              type: 'string',
              description: 'Instrument name',
            },
            depth: {
              type: 'number',
              description: 'Order book depth (number of levels)',
              default: 10,
            },
          },
          required: ['instrument_name'],
        },
      },
      {
        name: 'get_tradingview_chart',
        description: 'Get OHLC candlestick data for charting and technical analysis.',
        inputSchema: {
          type: 'object',
          properties: {
            instrument_name: {
              type: 'string',
              description: 'Instrument name',
            },
            resolution: {
              type: 'string',
              description: 'Chart resolution',
              enum: ['1', '3', '5', '10', '15', '30', '60', '120', '180', '360', '720', '1D'],
            },
            start_timestamp: {
              type: 'number',
              description: 'Start timestamp in milliseconds',
            },
            end_timestamp: {
              type: 'number',
              description: 'End timestamp in milliseconds',
            },
          },
          required: ['instrument_name', 'resolution', 'start_timestamp', 'end_timestamp'],
        },
      },
      {
        name: 'get_last_trades',
        description: 'Get recent trades for an instrument.',
        inputSchema: {
          type: 'object',
          properties: {
            instrument_name: {
              type: 'string',
              description: 'Instrument name',
            },
            count: {
              type: 'number',
              description: 'Number of trades to retrieve',
              default: 10,
            },
            include_old: {
              type: 'boolean',
              description: 'Include old trades',
              default: false,
            },
          },
          required: ['instrument_name'],
        },
      },
      {
        name: 'get_funding_rate_history',
        description: 'Get historical funding rate data for perpetual contracts.',
        inputSchema: {
          type: 'object',
          properties: {
            instrument_name: {
              type: 'string',
              description: 'Instrument name (must be perpetual)',
            },
            start_timestamp: {
              type: 'number',
              description: 'Start timestamp in milliseconds',
            },
            end_timestamp: {
              type: 'number',
              description: 'End timestamp in milliseconds',
            },
          },
          required: ['instrument_name', 'start_timestamp', 'end_timestamp'],
        },
      },
      {
        name: 'get_funding_rate_value',
        description: 'Get current funding rate for a perpetual contract.',
        inputSchema: {
          type: 'object',
          properties: {
            instrument_name: {
              type: 'string',
              description: 'Instrument name (must be perpetual)',
            },
            start_timestamp: {
              type: 'number',
              description: 'Start timestamp in milliseconds',
            },
            end_timestamp: {
              type: 'number',
              description: 'End timestamp in milliseconds',
            },
          },
          required: ['instrument_name', 'start_timestamp', 'end_timestamp'],
        },
      },
      {
        name: 'get_index_price',
        description: 'Get index price for a currency (spot price from multiple exchanges).',
        inputSchema: {
          type: 'object',
          properties: {
            index_name: {
              type: 'string',
              description: 'Index name (e.g., btc_usd, eth_usd)',
            },
          },
          required: ['index_name'],
        },
      },
      {
        name: 'get_volatility_index',
        description: 'Get volatility index data (DVOL) for options pricing.',
        inputSchema: {
          type: 'object',
          properties: {
            currency: {
              type: 'string',
              description: 'Currency symbol',
              enum: ['BTC', 'ETH'],
            },
            resolution: {
              type: 'string',
              description: 'Data resolution',
              enum: ['1', '60'],
            },
            start_timestamp: {
              type: 'number',
              description: 'Start timestamp in milliseconds',
            },
            end_timestamp: {
              type: 'number',
              description: 'End timestamp in milliseconds',
            },
          },
          required: ['currency'],
        },
      },
      {
        name: 'get_historical_volatility',
        description: 'Get historical volatility data for options analysis.',
        inputSchema: {
          type: 'object',
          properties: {
            currency: {
              type: 'string',
              description: 'Currency symbol',
              enum: ['BTC', 'ETH'],
            },
          },
          required: ['currency'],
        },
      },
      {
        name: 'get_book_summary_by_currency',
        description: 'Get book summary for all instruments of a currency including volume, open interest, and funding rates.',
        inputSchema: {
          type: 'object',
          properties: {
            currency: {
              type: 'string',
              description: 'Currency symbol',
              enum: ['BTC', 'ETH', 'USDC', 'USDT', 'EURR'],
            },
            kind: {
              type: 'string',
              description: 'Instrument kind',
              enum: ['future', 'option', 'spot', 'future_combo', 'option_combo'],
            },
          },
          required: ['currency'],
        },
      },
      {
        name: 'get_book_summary_by_instrument',
        description: 'Get detailed book summary for a specific instrument.',
        inputSchema: {
          type: 'object',
          properties: {
            instrument_name: {
              type: 'string',
              description: 'Instrument name',
            },
          },
          required: ['instrument_name'],
        },
      },
      {
        name: 'get_delivery_prices',
        description: 'Get delivery/settlement prices for expired futures and options.',
        inputSchema: {
          type: 'object',
          properties: {
            index_name: {
              type: 'string',
              description: 'Index name (e.g., btc_usd, eth_usd)',
            },
            offset: {
              type: 'number',
              description: 'Pagination offset',
              default: 0,
            },
            count: {
              type: 'number',
              description: 'Number of records',
              default: 100,
            },
          },
          required: ['index_name'],
        },
      },
      {
        name: 'ticker_statistics',
        description: 'Get statistical data about ticker performance over different time periods.',
        inputSchema: {
          type: 'object',
          properties: {
            currency: {
              type: 'string',
              description: 'Currency symbol',
              enum: ['BTC', 'ETH', 'USDC', 'USDT', 'EURR'],
            },
            kind: {
              type: 'string',
              description: 'Instrument kind',
              enum: ['future', 'option', 'spot'],
            },
          },
          required: ['currency'],
        },
      },
    ];
  }

  private async handleToolCall(name: string, args: any): Promise<any> {
    try {
      switch (name) {
        case 'get_instruments':
          return await this.getInstruments(args);
        case 'get_ticker':
          return await this.getTicker(args);
        case 'get_tickers':
          return await this.getTickers(args);
        case 'get_orderbook':
          return await this.getOrderbook(args);
        case 'get_tradingview_chart':
          return await this.getTradingViewChart(args);
        case 'get_last_trades':
          return await this.getLastTrades(args);
        case 'get_funding_rate_history':
          return await this.getFundingRateHistory(args);
        case 'get_funding_rate_value':
          return await this.getFundingRateValue(args);
        case 'get_index_price':
          return await this.getIndexPrice(args);
        case 'get_volatility_index':
          return await this.getVolatilityIndex(args);
        case 'get_historical_volatility':
          return await this.getHistoricalVolatility(args);
        case 'get_book_summary_by_currency':
          return await this.getBookSummaryByCurrency(args);
        case 'get_book_summary_by_instrument':
          return await this.getBookSummaryByInstrument(args);
        case 'get_delivery_prices':
          return await this.getDeliveryPrices(args);
        case 'ticker_statistics':
          return await this.getTickerStatistics(args);
        default:
          throw new Error(`Unknown tool: ${name}`);
      }
    } catch (error) {
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`,
          },
        ],
        isError: true,
      };
    }
  }

  private async getInstruments(args: any) {
    const result = await this.makeRequest('/public/get_instruments', {
      currency: args.currency !== 'any' ? args.currency : undefined,
      kind: args.kind,
      expired: args.expired,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getTicker(args: any) {
    const result = await this.makeRequest('/public/ticker', {
      instrument_name: args.instrument_name,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getTickers(args: any) {
    const result = await this.makeRequest('/public/get_book_summary_by_currency', {
      currency: args.currency,
      kind: args.kind,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getOrderbook(args: any) {
    const result = await this.makeRequest('/public/get_order_book', {
      instrument_name: args.instrument_name,
      depth: args.depth,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getTradingViewChart(args: any) {
    const result = await this.makeRequest('/public/get_tradingview_chart_data', {
      instrument_name: args.instrument_name,
      resolution: args.resolution,
      start_timestamp: args.start_timestamp,
      end_timestamp: args.end_timestamp,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getLastTrades(args: any) {
    const result = await this.makeRequest('/public/get_last_trades_by_instrument', {
      instrument_name: args.instrument_name,
      count: args.count,
      include_old: args.include_old,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getFundingRateHistory(args: any) {
    const result = await this.makeRequest('/public/get_funding_rate_history', {
      instrument_name: args.instrument_name,
      start_timestamp: args.start_timestamp,
      end_timestamp: args.end_timestamp,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getFundingRateValue(args: any) {
    const result = await this.makeRequest('/public/get_funding_rate_value', {
      instrument_name: args.instrument_name,
      start_timestamp: args.start_timestamp,
      end_timestamp: args.end_timestamp,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getIndexPrice(args: any) {
    const result = await this.makeRequest('/public/get_index_price', {
      index_name: args.index_name,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getVolatilityIndex(args: any) {
    const result = await this.makeRequest('/public/get_volatility_index_data', {
      currency: args.currency,
      resolution: args.resolution,
      start_timestamp: args.start_timestamp,
      end_timestamp: args.end_timestamp,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getHistoricalVolatility(args: any) {
    const result = await this.makeRequest('/public/get_historical_volatility', {
      currency: args.currency,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getBookSummaryByCurrency(args: any) {
    const result = await this.makeRequest('/public/get_book_summary_by_currency', {
      currency: args.currency,
      kind: args.kind,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getBookSummaryByInstrument(args: any) {
    const result = await this.makeRequest('/public/get_book_summary_by_instrument', {
      instrument_name: args.instrument_name,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getDeliveryPrices(args: any) {
    const result = await this.makeRequest('/public/get_delivery_prices', {
      index_name: args.index_name,
      offset: args.offset,
      count: args.count,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  private async getTickerStatistics(args: any) {
    const result = await this.makeRequest('/public/ticker', {
      currency: args.currency,
      kind: args.kind,
    });

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  }

  async run(): Promise<void> {
    if (this.config.apiKey && this.config.apiSecret) {
      await this.authenticate();
    }

    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('Deribit MCP Server running on stdio');
  }
}

// Initialize and run server
const config: DeribitConfig = {
  apiKey: process.env.DERIBIT_API_KEY,
  apiSecret: process.env.DERIBIT_API_SECRET,
  testnet: process.env.DERIBIT_TESTNET === 'true',
};

const server = new DeribitMCPServer(config);
server.run().catch(console.error);