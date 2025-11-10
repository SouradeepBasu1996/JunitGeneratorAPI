package com.online.market.marketStore.repository;

import com.online.market.marketStore.entity.Order;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

@ExtendWith(MockitoExtension.class)
public class OrderRepositoryTest {

    @Mock
    private Order order;

    @InjectMocks
    private OrderRepository orderRepository;

    @BeforeEach
    void setUp() {
        Mockito.reset(order);
    }

    @Test
    public void testFindAllOrders_expectedList_scenario() {
        // Arrange
        Mockito.when(orderRepository.findAll()).thenReturn(List.of(order));

        // Act
        List<Order> orders = orderRepository.findAll();

        // Assert
        assertEquals(1, orders.size());
        assertNotNull(orders);
    }

    @Test
    public void testFindOrderById_expectedOptional_scenario() {
        // Arrange
        Mockito.when(orderRepository.findById(1L)).thenReturn(Optional.of(order));

        // Act
        Optional<Order> order = orderRepository.findById(1L);

        // Assert
        assertEquals(Optional.of(order), order);
    }

    @Test
    public void testSaveOrder_expectedSavedOrder_scenario() {
        // Arrange
        Order savedOrder = Mockito.mock(Order.class);
        Mockito.when(orderRepository.save(order)).thenReturn(savedOrder);

        // Act
        Order saved = orderRepository.save(order);

        // Assert
        assertEquals(savedOrder, saved);
    }
}